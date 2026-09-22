"""The single path from this application to Claude.

One function makes every model call: it streams (so a long research round cannot trip
an HTTP timeout), asks for structured output, declares the web search tool when the
round needs research, and returns a validated model plus what the call consumed.

Nothing here patches a bad reply. A reply that does not validate is an error.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from bie import fixtures
from bie.budget import record_spend
from bie.config import Settings
from bie.errors import BieError, InvalidModelOutput, RateLimited, UpstreamError, UpstreamTimeout
from bie.pricing import cost_usd
from bie.schemas import ResearchStatus, Source, Usage

T = TypeVar("T", bound=BaseModel)

# Dynamic filtering keeps retrieved pages out of the context window unless they matter.
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"


@dataclass
class ModelReply:
    parsed: BaseModel
    usage: Usage
    sources: list[Source] = field(default_factory=list)
    research_status: ResearchStatus = "unavailable"


def build_client(api_key: str | None = None) -> anthropic.Anthropic:
    """Credentials come from the environment; never from an argument in normal use."""
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def research_tools(settings: Settings) -> list[dict]:
    return [
        {
            "type": WEB_SEARCH_TOOL_TYPE,
            "name": "web_search",
            "max_uses": settings.max_searches,
        }
    ]


def translate_error(exc: Exception) -> BieError:
    """SDK failures become founder-readable errors with no internal detail attached."""
    if isinstance(exc, anthropic.RateLimitError):
        return RateLimited(
            "The evaluator is busy right now. Wait a moment and try again.",
            detail=repr(exc),
        )
    if isinstance(exc, anthropic.APITimeoutError):
        return UpstreamTimeout(
            "The evaluation took too long and was cut off. Try again.", detail=repr(exc)
        )
    return UpstreamError("We could not reach the evaluator. Try again.", detail=repr(exc))


def _text_blocks(message: Any) -> list[str]:
    return [b.text for b in getattr(message, "content", []) if getattr(b, "type", "") == "text"]


def _parse(message: Any, schema: type[T]) -> T:
    parsed = getattr(message, "parsed_output", None)
    if isinstance(parsed, schema):
        return parsed
    candidates = list(reversed(_text_blocks(message)))
    if not candidates:
        raise InvalidModelOutput(
            "The evaluator returned nothing we could read. Try again.",
            detail="no text blocks in response",
        )
    last_error: Exception | None = None
    for text in candidates:
        try:
            return schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
    raise InvalidModelOutput(
        "The evaluator's reply was incomplete, so we are not showing it. Try again.",
        detail=f"{type(last_error).__name__}: {last_error}",
    )


def _read_research(message: Any) -> tuple[list[Source], ResearchStatus, int]:
    """Search results are data on the response, not exceptions (see research.md §5)."""
    sources: list[Source] = []
    saw_result = False
    saw_error = False
    now = datetime.now(UTC)

    for block in getattr(message, "content", []):
        if getattr(block, "type", "") != "web_search_tool_result":
            continue
        content = getattr(block, "content", None)
        if isinstance(content, list):
            saw_result = True
            for item in content:
                url = getattr(item, "url", None)
                if url:
                    sources.append(
                        Source(url=url, title=getattr(item, "title", "") or "", accessed_at=now)
                    )
        else:
            # An error result: content is a single object carrying error_code.
            saw_error = True

    if saw_error:
        status: ResearchStatus = "degraded"
    elif saw_result:
        status = "ok"
    else:
        status = "unavailable"
    return sources, status, len(sources)


def _usage(message: Any, searches: int) -> Usage:
    raw = getattr(message, "usage", None)
    model = getattr(message, "model", "unknown")
    server = getattr(raw, "server_tool_use", None)
    web_searches = getattr(server, "web_search_requests", 0) if server else 0
    usage = Usage(
        model=model,
        input_tokens=getattr(raw, "input_tokens", 0) or 0,
        output_tokens=getattr(raw, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
        web_searches=web_searches or searches,
    )
    usage.cost_usd = cost_usd(
        usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        web_searches=usage.web_searches,
    )
    return usage


def build_system(prompt: str, instruction: str | None = None) -> list[dict]:
    """The prompt is the cached prefix; the per-step instruction follows it, uncached."""
    blocks: list[dict] = [
        {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}
    ]
    if instruction:
        blocks.append({"type": "text", "text": instruction})
    return blocks


def complete(
    client: Any,
    *,
    system: str,
    messages: list[dict],
    schema: type[T],
    effort: str,
    settings: Settings,
    research: bool = False,
    instruction: str | None = None,
) -> ModelReply:
    """One round trip: stream, finalise, validate, and report what it cost."""
    kwargs: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "system": build_system(system, instruction),
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "output_format": schema,
    }
    if research:
        kwargs["tools"] = research_tools(settings)

    started = time.monotonic()
    replay = fixtures.replay_path()
    if replay is not None:
        # No call, no charge: the reply comes off disk exactly as it arrived.
        message: Any = fixtures.load(replay)
        return _finish(message, schema, research, started, recorded=False)

    try:
        with client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
    except BieError:
        raise
    except ValidationError as exc:
        # The SDK validates output_format for us, so a malformed reply lands here
        # rather than in _parse. It is a bad reply, not a bad connection.
        raise InvalidModelOutput(
            "The evaluator's reply did not fit the required shape, so we are not showing "
            "it. Try again.",
            detail=str(exc),
        ) from exc
    except Exception as exc:  # SDK and transport failures alike
        raise translate_error(exc) from exc

    if fixtures.recording_enabled():
        fixtures.record(message, label="reply")
    return _finish(message, schema, research, started)


def _finish(
    message: Any, schema: type[T], research: bool, started: float, *, recorded: bool = True
) -> ModelReply:
    """Account for the call before validating it.

    The call is billed the moment it returns, whether or not the reply is usable. Costing
    it only on success let expensive failures escape the session and daily ledgers, and
    made the spend reported to the founder smaller than the spend on the bill.
    """
    sources, status, found = _read_research(message)
    usage = _usage(message, found)
    usage.latency_ms = int((time.monotonic() - started) * 1000)
    if recorded:
        record_spend(usage.cost_usd)
    try:
        parsed = _parse(message, schema)
    except InvalidModelOutput as exc:
        exc.usage = usage  # the caller can still report what the failure cost
        raise
    return ModelReply(
        parsed=parsed,
        usage=usage,
        sources=sources,
        research_status=status if research else "unavailable",
    )
