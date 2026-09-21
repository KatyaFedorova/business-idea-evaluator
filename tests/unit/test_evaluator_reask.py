"""T043 — vague answers come back as questions, not as a verdict built on guesses."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bie.config import Settings
from bie.evaluator import evaluate
from bie.schemas import FounderMessage, QuestionSet, Round, RoundDecision

IDEA = "A subscription app that shames you with your own voice when you doomscroll daily."


def _rounds(valid_question_set) -> list[Round]:
    return [
        Round(
            index=0,
            kind="questions",
            submission=[FounderMessage(text=IDEA)],
            questions=QuestionSet.model_validate(valid_question_set),
        )
    ]


def _decision(**kwargs) -> str:
    return json.dumps(kwargs)


def test_a_reask_decision_becomes_a_reask_round(fake_anthropic, valid_question_set):
    valid_question_set["note"] = "'Everyone in an office' is not a customer."
    client = fake_anthropic(_decision(decision="reask", reask=valid_question_set, report=None))
    round_ = evaluate(
        IDEA,
        rounds=_rounds(valid_question_set),
        answers=[FounderMessage(text="everyone who works in an office")],
        client=client,
        settings=Settings(),
    )
    assert round_.kind == "reask"
    assert round_.report is None
    assert round_.questions.note


def test_a_verdict_decision_becomes_a_verdict_round(
    fake_anthropic, valid_question_set, valid_verdict
):
    client = fake_anthropic(_decision(decision="verdict", reask=None, report=valid_verdict))
    round_ = evaluate(
        IDEA,
        rounds=_rounds(valid_question_set),
        answers=[FounderMessage(text="A real, specific answer about paying customers.")],
        client=client,
        settings=Settings(),
    )
    assert round_.kind == "verdict"
    assert round_.report.verdict == "DONT_PROCEED"


def test_a_reask_without_a_note_is_rejected(valid_question_set):
    with pytest.raises(ValidationError):
        RoundDecision.model_validate(
            {"decision": "reask", "reask": valid_question_set, "report": None}
        )


def test_a_decision_must_carry_what_it_claims(valid_verdict, valid_question_set):
    noted = {**valid_question_set, "note": "too vague"}
    with pytest.raises(ValidationError, match="reask"):
        RoundDecision.model_validate({"decision": "reask", "reask": None, "report": valid_verdict})
    with pytest.raises(ValidationError, match="report"):
        RoundDecision.model_validate({"decision": "verdict", "reask": noted, "report": None})
    with pytest.raises(ValidationError, match="reask"):
        RoundDecision.model_validate(
            {"decision": "verdict", "reask": noted, "report": valid_verdict}
        )


def test_the_loop_stops_asking_after_the_configured_limit(
    fake_anthropic, valid_question_set, valid_verdict, monkeypatch
):
    """Edge case: a founder who keeps answering vaguely must not be asked forever."""
    monkeypatch.setenv("BIE_MAX_REASKS", "1")
    rounds = _rounds(valid_question_set)
    reask = QuestionSet.model_validate({**valid_question_set, "note": "still vague"})
    rounds.append(Round(index=1, kind="reask", questions=reask))
    client = fake_anthropic(_decision(decision="verdict", reask=None, report=valid_verdict))
    round_ = evaluate(
        IDEA,
        rounds=rounds,
        answers=[FounderMessage(text="still vague")],
        client=client,
        settings=Settings(),
    )
    instruction = client.messages.calls[-1]["system"][-1]["text"]
    assert "last round of questions" in instruction.lower() or "must give" in instruction.lower()
    assert round_.kind == "verdict"
