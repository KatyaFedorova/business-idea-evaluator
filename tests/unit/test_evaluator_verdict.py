"""T026 — round two researches, then delivers the verdict."""

from __future__ import annotations

import json

import pytest

from bie.budget import BudgetExceeded
from bie.config import Settings
from bie.evaluator import evaluate
from bie.schemas import FounderMessage, QuestionSet, Round


def decision(report: dict) -> str:
    """Step two answers with a decision envelope; a verdict is one of its two shapes."""
    return json.dumps({"decision": "verdict", "reask": None, "report": report})
from tests.conftest import search_error_block, search_result_block, text_of

IDEA = "A subscription app that shames you with your own voice when you doomscroll."


def _question_round(valid_question_set) -> Round:
    return Round(
        index=0,
        kind="questions",
        submission=[FounderMessage(text=IDEA)],
        questions=QuestionSet.model_validate(valid_question_set),
    )


def _answers() -> list[FounderMessage]:
    return [FounderMessage(text="1. People who quit three blockers. 2. They uninstall them.")]


def test_returns_a_verdict_round(fake_anthropic, valid_question_set, valid_verdict):
    client = fake_anthropic(
        decision(valid_verdict),
        extra_blocks=[search_result_block(("https://example.com/opal", "Opal"))],
    )
    round_ = evaluate(
        IDEA,
        rounds=[_question_round(valid_question_set)],
        answers=_answers(),
        client=client,
        settings=Settings(),
    )
    assert round_.kind == "verdict"
    assert round_.index == 1
    assert round_.report.verdict == "DONT_PROCEED"
    assert round_.research_status == "ok"
    assert [s.url for s in round_.sources] == ["https://example.com/opal"]
    assert round_.cost_usd > 0


def test_the_whole_transcript_is_sent(fake_anthropic, valid_question_set, valid_verdict):
    client = fake_anthropic(decision(valid_verdict))
    evaluate(
        IDEA,
        rounds=[_question_round(valid_question_set)],
        answers=_answers(),
        client=client,
        settings=Settings(),
    )
    messages = client.messages.calls[-1]["messages"]
    assert messages[0]["role"] == "user" and IDEA in text_of(messages[0]["content"])
    assert messages[1]["role"] == "assistant"
    assert "1." in messages[1]["content"]  # the questions that were asked
    assert messages[-1]["role"] == "user" and "[ANSWER]" in text_of(messages[-1]["content"])


def test_verdict_rounds_research_at_high_effort(fake_anthropic, valid_question_set, valid_verdict):
    client = fake_anthropic(decision(valid_verdict))
    evaluate(
        IDEA,
        rounds=[_question_round(valid_question_set)],
        answers=_answers(),
        client=client,
        settings=Settings(),
    )
    call = client.messages.calls[-1]
    assert call["tools"][0]["name"] == "web_search"
    assert call["output_config"]["effort"] == "high"


def test_degraded_research_still_produces_a_verdict(
    fake_anthropic, valid_question_set, valid_verdict
):
    client = fake_anthropic(
        decision(valid_verdict), extra_blocks=[search_error_block("too_many_requests")]
    )
    round_ = evaluate(
        IDEA,
        rounds=[_question_round(valid_question_set)],
        answers=_answers(),
        client=client,
        settings=Settings(),
    )
    assert round_.research_status == "degraded"
    assert round_.report is not None


def test_unavailable_research_still_produces_a_verdict(
    fake_anthropic, valid_question_set, valid_verdict
):
    client = fake_anthropic(decision(valid_verdict))
    round_ = evaluate(
        IDEA,
        rounds=[_question_round(valid_question_set)],
        answers=_answers(),
        client=client,
        settings=Settings(),
    )
    assert round_.research_status == "unavailable"
    assert round_.report is not None


def test_the_round_is_refused_when_it_would_cost_too_much(
    fake_anthropic, valid_question_set, valid_verdict, monkeypatch
):
    monkeypatch.setenv("BIE_MAX_COST_PER_ROUND_USD", "0.001")
    client = fake_anthropic(decision(valid_verdict))
    with pytest.raises(BudgetExceeded):
        evaluate(
            IDEA,
            rounds=[_question_round(valid_question_set)],
            answers=_answers(),
            client=client,
            settings=Settings(),
        )
    assert not any("messages" in c and "tools" in c for c in client.messages.calls)


def test_the_session_ceiling_counts_what_was_already_spent(
    fake_anthropic, valid_question_set, valid_verdict
):
    client = fake_anthropic(decision(valid_verdict))
    with pytest.raises(BudgetExceeded):
        evaluate(
            IDEA,
            rounds=[_question_round(valid_question_set)],
            answers=_answers(),
            client=client,
            settings=Settings(),
            spent=4.99,
        )


def test_research_can_be_switched_off_entirely(
    fake_anthropic, valid_question_set, valid_verdict, monkeypatch
):
    """BIE_MAX_SEARCHES=0 is the fast, cheap path for iterating on the UI.

    The verdict still arrives, but it must be told it has no sources so it does not
    present recalled knowledge as something it looked up.
    """
    monkeypatch.setenv("BIE_MAX_SEARCHES", "0")
    settings = Settings()
    assert settings.research_enabled is False

    client = fake_anthropic(decision(valid_verdict))
    round_ = evaluate(
        IDEA,
        rounds=[_question_round(valid_question_set)],
        answers=_answers(),
        client=client,
        settings=settings,
    )
    call = client.messages.calls[-1]
    assert not call.get("tools")
    assert "Research is switched off" in call["system"][-1]["text"]
    assert round_.report is not None
    assert round_.research_status == "unavailable"


def test_a_negative_search_budget_is_still_rejected(monkeypatch):
    monkeypatch.setenv("BIE_MAX_SEARCHES", "-1")
    with pytest.raises(ValueError):
        Settings()
