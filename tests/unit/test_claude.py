"""T017 — the model-call layer: usage, sources, research status, failure translation."""

from __future__ import annotations

import json

import anthropic
import pytest

from bie.claude import ModelReply, complete, translate_error
from bie.config import Settings
from bie.errors import InvalidModelOutput, RateLimited, UpstreamError, UpstreamTimeout
from bie.schemas import QuestionSet
from tests.conftest import search_error_block, search_result_block


def _reply(client, **kwargs) -> ModelReply:
    return complete(
        client,
        system="system prompt",
        messages=[{"role": "user", "content": "idea"}],
        schema=QuestionSet,
        effort="medium",
        settings=Settings(),
        **kwargs,
    )


def test_parses_and_validates_the_reply(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    reply = _reply(client)
    assert isinstance(reply.parsed, QuestionSet)
    assert len(reply.parsed.questions) == 7


def test_usage_is_mapped_including_searches(fake_anthropic, valid_question_set):
    from tests.conftest import FakeServerToolUse

    client = fake_anthropic(
        json.dumps(valid_question_set),
        input_tokens=2000,
        output_tokens=1000,
        cache_read_input_tokens=500,
        server_tool_use=FakeServerToolUse(web_search_requests=3),
    )
    usage = _reply(client, research=True).usage
    assert usage.model == "claude-opus-5"
    assert usage.input_tokens == 2000
    assert usage.output_tokens == 1000
    assert usage.cache_read_tokens == 500
    assert usage.web_searches == 3
    assert usage.cost_usd > 0


def test_sources_come_from_search_results(fake_anthropic, valid_question_set):
    client = fake_anthropic(
        json.dumps(valid_question_set),
        extra_blocks=[
            search_result_block(
                ("https://example.com/a", "Competitor A"),
                ("https://example.com/b", "Competitor B"),
            )
        ],
    )
    reply = _reply(client, research=True)
    assert [s.url for s in reply.sources] == ["https://example.com/a", "https://example.com/b"]
    assert reply.research_status == "ok"


def test_a_search_error_degrades_rather_than_raises(fake_anthropic, valid_question_set):
    client = fake_anthropic(
        json.dumps(valid_question_set),
        extra_blocks=[
            search_result_block(("https://example.com/a", "A")),
            search_error_block("too_many_requests"),
        ],
    )
    reply = _reply(client, research=True)
    assert reply.research_status == "degraded"
    assert reply.parsed is not None


def test_no_search_blocks_means_research_was_unavailable(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    assert _reply(client, research=True).research_status == "unavailable"


def test_research_tool_is_declared_and_capped(fake_anthropic, valid_question_set, monkeypatch):
    monkeypatch.setenv("BIE_MAX_SEARCHES", "4")
    client = fake_anthropic(json.dumps(valid_question_set))
    complete(
        client,
        system="s",
        messages=[{"role": "user", "content": "i"}],
        schema=QuestionSet,
        effort="high",
        settings=Settings(),
        research=True,
    )
    tools = client.messages.calls[0]["tools"]
    assert tools[0]["type"] == "web_search_20260209"
    assert tools[0]["max_uses"] == 4


def test_no_tools_when_research_is_off(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    _reply(client)
    assert not client.messages.calls[0].get("tools")


def test_system_prompt_is_cached(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    _reply(client)
    system = client.messages.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_unparseable_reply_is_rejected(fake_anthropic):
    client = fake_anthropic("this is not json at all")
    with pytest.raises(InvalidModelOutput):
        _reply(client)


def test_schema_violation_is_rejected_not_patched(fake_anthropic, valid_question_set):
    valid_question_set["questions"] = valid_question_set["questions"][:1]
    client = fake_anthropic(json.dumps(valid_question_set))
    with pytest.raises(InvalidModelOutput):
        _reply(client)


@pytest.mark.parametrize(
    ("sdk_error", "expected"),
    [
        (anthropic.RateLimitError, RateLimited),
        (anthropic.APITimeoutError, UpstreamTimeout),
        (anthropic.APIStatusError, UpstreamError),
        (anthropic.APIConnectionError, UpstreamError),
    ],
)
def test_sdk_failures_are_translated(sdk_error, expected):
    err = translate_error(sdk_error.__new__(sdk_error))
    assert isinstance(err, expected)
    assert err.retryable is True
    assert "sk-ant" not in err.message


def test_a_reply_the_sdk_rejects_is_invalid_output_not_an_upstream_error(fake_anthropic):
    """The SDK validates output_format itself, so its ValidationError lands on the call.

    Regression: that used to be reported as a 502 upstream failure, which told the
    founder the service was unreachable when in fact the reply was simply wrong.
    """
    from pydantic import ValidationError as PydanticValidationError

    from tests.conftest import FakeAnthropic

    try:
        QuestionSet.model_validate({"questions": []})
    except PydanticValidationError as exc:
        error = exc

    client = FakeAnthropic(error)
    with pytest.raises(InvalidModelOutput):
        _reply(client)
