"""The eval graders are pure functions, so they are tested like anything else."""

from __future__ import annotations

import pytest

from bie.schemas import FounderMessage, QuestionSet, Round, Source, VerdictReport
from evals import graders


def question_round(valid_question_set, **kw) -> Round:
    return Round(
        index=0,
        kind=kw.pop("kind", "questions"),
        submission=[FounderMessage(text="idea")],
        questions=QuestionSet.model_validate(valid_question_set),
        **kw,
    )


def verdict_round(valid_verdict, **kw) -> Round:
    return Round(
        index=1,
        kind="verdict",
        report=VerdictReport.model_validate(valid_verdict),
        research_status=kw.pop("research_status", "ok"),
        sources=kw.pop("sources", [Source(url="https://example.com", title="Opal")]),
        **kw,
    )


def test_clean_question_round_passes(valid_question_set):
    round_ = question_round(valid_question_set)
    assert graders.no_verdict_in_questions(round_).passed
    assert graders.covers_priority_topics(round_).passed


def test_a_verdict_round_fails_the_step_one_grader(valid_verdict):
    assert not graders.no_verdict_in_questions(verdict_round(valid_verdict)).passed


def test_report_structure_and_length(valid_verdict):
    round_ = verdict_round(valid_verdict)
    assert graders.report_structure(round_).passed
    assert graders.within_word_limit(round_).passed
    assert graders.guesses_are_labelled(round_).passed
    assert graders.names_prior_art(round_).passed
    assert graders.sources_are_real(round_).passed


def test_padding_is_caught(valid_verdict):
    valid_verdict["works_because"][0] = "This has real potential and the market is huge"
    assert not graders.no_padding(verdict_round(valid_verdict)).passed


def test_forced_verdict_is_caught(valid_verdict):
    valid_verdict["verdict"] = "PROCEED"
    assert not graders.verdict_is(verdict_round(valid_verdict), forbidden="PROCEED").passed


def test_degraded_research_must_be_declared(valid_verdict):
    round_ = verdict_round(valid_verdict, research_status="unavailable", sources=[])
    assert graders.degraded_research_is_declared(round_).passed
    valid_verdict["missing_data"] = []
    for failure in valid_verdict["fails_because"]:
        failure["is_guess"] = False
    bare = verdict_round(valid_verdict, research_status="unavailable", sources=[])
    assert not graders.degraded_research_is_declared(bare).passed


def test_attachment_grounding(valid_verdict):
    valid_verdict["riskiest_assumption"] = "Only 14 of 180 February signups paid."
    round_ = verdict_round(valid_verdict)
    assert graders.references_attachment(round_, ["14 of 180"]).passed
    assert not graders.references_attachment(round_, ["99 of 100"]).passed


@pytest.mark.parametrize("kind", ["questions", "verdict"])
def test_reask_grader_only_passes_on_a_reask(valid_question_set, valid_verdict, kind):
    round_ = (
        question_round(valid_question_set)
        if kind == "questions"
        else verdict_round(valid_verdict)
    )
    assert not graders.reask_rather_than_verdict(round_).passed


def test_reask_grader_passes_on_a_noted_reask(valid_question_set):
    valid_question_set["note"] = "'Everyone in an office' is not a customer."
    round_ = question_round(valid_question_set, kind="reask")
    assert graders.reask_rather_than_verdict(round_).passed
