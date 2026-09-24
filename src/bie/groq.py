"""Groq, dressed as the slice of the Anthropic client this app uses.

The evaluator, the budget and the eval suite call `client.messages.stream`,
`client.messages.count_tokens` and `client.files`. This module answers those same calls
from Groq's OpenAI-compatible chat endpoint, so switching provider is one setting and
nothing upstream changes.

What an open model on Groq does not have, and how that is handled:
- web search: none. Settings turn research off, so the verdict says nothing was verified.
- guaranteed structured output: JSON mode plus the schema in the system prompt, then the
  same pydantic validation as before. One retry, told what failed, before giving up.
- images and PDFs: not read. They arrive as "could not be read"; sheets and text still work.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Self

from pydantic import BaseModel, ValidationError

from bie.errors import BieError, RateLimited, UpstreamError, UpstreamTimeout

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_S = 120
# The free tier allows 8,000 tokens a minute and one round is about 4,000, so waiting
# out a rate limit is the normal path, not the exception. Give up after a minute and a half.
MAX_RATE_LIMIT_WAIT_S = 90
RATE_LIMIT_ATTEMPTS = 8


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class GroqUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class GroqMessage:
    """Shaped like an Anthropic Message: content blocks, usage, model."""

    content: list[TextBlock]
    usage: GroqUsage = field(default_factory=GroqUsage)
    model: str = ""
    stop_reason: str = "end_turn"


class _Done:
    """`with client.messages.stream(...) as s: s.get_final_message()` without streaming."""

    def __init__(self, message: GroqMessage) -> None:
        self._message = message

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> GroqMessage:
        return self._message


class NotSupportedOnGroq(Exception):
    """Raised for files: an attachment the open model cannot read is marked unreadable."""


def _text_of(content: Any) -> str:
    """Anthropic content (a string or a list of blocks) as plain text. Files are dropped."""
    if isinstance(content, str):
        return content
    return "\n\n".join(
        b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"
    )


def _schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "OUTPUT FORMAT: reply with one JSON object and nothing else, valid against this JSON "
        "schema. Respect every maxLength, minItems and maxItems exactly; shorten rather than "
        "overrun.\n" + json.dumps(schema.model_json_schema())
    )


def to_chat_messages(
    system: Any, messages: list[dict], schema: type[BaseModel] | None
) -> list[dict]:
    system_text = _text_of(system)
    if schema is not None:
        system_text += "\n\n" + _schema_instruction(schema)
    chat = [{"role": "system", "content": system_text}]
    chat += [{"role": m["role"], "content": _text_of(m["content"])} for m in messages]
    return chat


class _Messages:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            GROQ_URL,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # Groq's edge rejects urllib's default agent with a 403 (Cloudflare 1010).
                "User-Agent": "business-idea-evaluator/0.1",
            },
        )
        waited = 0.0
        for _ in range(RATE_LIMIT_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:400]
                if exc.code == 429:
                    wait = max(float(exc.headers.get("retry-after") or 0), 2.0) + 1.0
                    if waited + wait <= MAX_RATE_LIMIT_WAIT_S:
                        time.sleep(wait)
                        waited += wait
                        continue
                    raise RateLimited(
                        "The free model is rate limited right now. Wait a minute and try again.",
                        detail=detail,
                    ) from exc
                raise UpstreamError(
                    "We could not reach the evaluator. Try again.", detail=f"{exc.code} {detail}"
                ) from exc
            except TimeoutError as exc:
                raise UpstreamTimeout(
                    "The evaluation took too long and was cut off. Try again.", detail=repr(exc)
                ) from exc
            except urllib.error.URLError as exc:
                raise UpstreamError(
                    "We could not reach the evaluator. Try again.", detail=repr(exc)
                ) from exc
        raise RateLimited(
            "The free model is rate limited right now. Wait a minute and try again.",
            detail=f"still limited after {RATE_LIMIT_ATTEMPTS} attempts",
        )

    def _call(self, model: str, chat: list[dict], max_tokens: int, json_mode: bool) -> dict:
        body: dict[str, Any] = {
            "model": model,
            "messages": chat,
            "max_completion_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return self._post(body)

    def stream(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[dict],
        output_format: type[BaseModel] | None = None,
        **_ignored: Any,  # thinking, effort and tools have no Groq equivalent
    ) -> _Done:
        chat = to_chat_messages(system, messages, output_format)
        usage = GroqUsage()
        text = ""
        for attempt in range(2):
            reply = self._call(model, chat, max_tokens, json_mode=output_format is not None)
            raw_usage = reply.get("usage") or {}
            usage.input_tokens += raw_usage.get("prompt_tokens", 0)
            usage.output_tokens += raw_usage.get("completion_tokens", 0)
            text = reply["choices"][0]["message"].get("content") or ""
            if output_format is None:
                break
            try:
                output_format.model_validate(json.loads(text))
                break
            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt == 1:
                    break  # complete() raises InvalidModelOutput on the bad reply
                chat += [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "That JSON failed validation. Fix exactly this and reply "
                        f"with the corrected JSON object only:\n{str(exc)[:1500]}",
                    },
                ]
        return _Done(GroqMessage(content=[TextBlock(text=text)], usage=usage, model=model))

    def count_tokens(self, *, system: Any, messages: list[dict], **_ignored: Any) -> Any:
        """No counting endpoint; four characters a token is close enough for a free model."""
        chars = len(_text_of(system)) + sum(len(_text_of(m["content"])) for m in messages)
        return type("TokenCount", (), {"input_tokens": chars // 4})()


class _Files:
    def upload(self, **_ignored: Any) -> Any:
        raise NotSupportedOnGroq("images and PDFs are not read by the open model")

    def delete(self, *_ignored: Any) -> None:
        return None


class GroqClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise BieError("No GROQ_API_KEY is set, so the evaluator cannot run.")
        self.messages = _Messages(key)
        self.files = _Files()
