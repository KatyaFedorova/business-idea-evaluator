"""T007 — the model contract. Every rule here is quoted from data-model.md."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bie.schemas import (
    Attachment,
    FailureMode,
    Question,
    QuestionSet,
    ReAsk,
    ValidationPlan,
    VerdictReport,
)


# --- QuestionSet ----------------------------------------------------------- #
def test_valid_question_set(valid_question_set):
    qs = QuestionSet.model_validate(valid_question_set)
    assert len(qs.questions) == 7
    assert qs.questions[0].number == 1


def test_question_number_must_be_at_least_one():
    with pytest.raises(ValidationError):
        Question(number=0, text="Who?", topic="customer")


@pytest.mark.parametrize("count", [2, 11])
def test_question_set_holds_three_to_ten_questions(count):
    payload = {
        "questions": [{"number": i + 1, "text": f"Q{i}?", "topic": "other"} for i in range(count)]
    }
    with pytest.raises(ValidationError):
        QuestionSet.model_validate(payload)


def test_question_numbers_must_be_contiguous_from_one(valid_question_set):
    valid_question_set["questions"][2]["number"] = 9
    with pytest.raises(ValidationError, match="contiguous"):
        QuestionSet.model_validate(valid_question_set)


@pytest.mark.parametrize(
    "text",
    [
        "VERDICT: PROCEED, but first tell me who the customer is.",
        "My verdict is that you should not proceed. Who is the customer?",
        "DON'T PROCEED — who is the customer?",
        "PROCEED ONLY AFTER TESTING pricing. Who is the customer?",
    ],
)
def test_step_one_cannot_leak_a_verdict(valid_question_set, text):
    """FR-004: the first response must contain no verdict or evaluative judgement."""
    valid_question_set["questions"][0]["text"] = text
    with pytest.raises(ValidationError, match="verdict"):
        QuestionSet.model_validate(valid_question_set)


def test_ordinary_use_of_the_word_proceed_is_allowed(valid_question_set):
    valid_question_set["questions"][0]["text"] = "How would you proceed if nobody replies?"
    assert QuestionSet.model_validate(valid_question_set)


def test_reask_requires_a_note(valid_question_set):
    with pytest.raises(ValidationError, match="note"):
        ReAsk.model_validate(valid_question_set)
    valid_question_set["note"] = "'Everyone in an office' is not a customer."
    assert ReAsk.model_validate(valid_question_set).note


# --- VerdictReport --------------------------------------------------------- #
def test_valid_verdict(valid_verdict):
    report = VerdictReport.model_validate(valid_verdict)
    assert report.verdict == "DONT_PROCEED"
    assert report.prior_art == ["Opal", "one sec"]


def test_conditional_verdict_requires_its_condition(valid_verdict):
    valid_verdict["verdict"] = "PROCEED_ONLY_AFTER_TESTING"
    with pytest.raises(ValidationError, match="verdict_condition"):
        VerdictReport.model_validate(valid_verdict)
    valid_verdict["verdict_condition"] = "that 10 of 50 people pre-pay"
    assert VerdictReport.model_validate(valid_verdict)


def test_condition_is_rejected_on_an_unconditional_verdict(valid_verdict):
    valid_verdict["verdict_condition"] = "something"
    with pytest.raises(ValidationError, match="verdict_condition"):
        VerdictReport.model_validate(valid_verdict)


@pytest.mark.parametrize("field", ["works_because", "fails_because"])
def test_exactly_three_reasons(valid_verdict, field):
    valid_verdict[field] = valid_verdict[field][:2]
    with pytest.raises(ValidationError):
        VerdictReport.model_validate(valid_verdict)


def test_failure_modes_are_ranked_one_to_three(valid_verdict):
    valid_verdict["fails_because"][2]["rank"] = 2
    with pytest.raises(ValidationError, match="rank"):
        VerdictReport.model_validate(valid_verdict)


def test_failure_mode_rank_is_bounded():
    with pytest.raises(ValidationError):
        FailureMode(rank=4, text="x", is_guess=False)


def test_validation_plan_must_fit_two_weeks_and_need_no_code():
    base = {
        "assumption_tested": "a",
        "steps": ["s"],
        "who_to_talk_to": "b",
        "pass_threshold": "c",
        "fail_threshold": "d",
        "duration_days": 14,
        "requires_code": False,
    }
    assert ValidationPlan.model_validate(base)
    with pytest.raises(ValidationError):
        ValidationPlan.model_validate({**base, "duration_days": 15})
    with pytest.raises(ValidationError):
        ValidationPlan.model_validate({**base, "requires_code": True})
    with pytest.raises(ValidationError):
        ValidationPlan.model_validate({**base, "steps": []})


def test_research_directions_and_kill_criteria_are_bounded(valid_verdict):
    valid_verdict["kill_criteria"] = []
    with pytest.raises(ValidationError):
        VerdictReport.model_validate(valid_verdict)


def test_guesses_are_labelled(valid_verdict):
    report = VerdictReport.model_validate(valid_verdict)
    assert report.fails_because[2].is_guess is True
    assert report.missing_data == ["Retention curves for screen-time apps"]


def test_report_is_rejected_when_it_runs_long(valid_verdict):
    valid_verdict["riskiest_assumption"] = "word " * 1000
    with pytest.raises(ValidationError, match="900"):
        VerdictReport.model_validate(valid_verdict)


def test_word_count_is_computed(valid_verdict):
    assert 0 < VerdictReport.model_validate(valid_verdict).word_count < 900


# --- Attachment ------------------------------------------------------------ #
def test_attachment_defaults():
    a = Attachment(id="1", filename="a.png", kind="image", size_bytes=10, file_id="file_x")
    assert a.readable is True
    assert a.error is None
