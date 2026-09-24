"""The quality rubric: loading, weighting and the judge call, with no network."""

from __future__ import annotations

import json

from bie.config import Settings
from bie.schemas import FounderMessage, QuestionSet, Round, VerdictReport
from evals.rubric import load_rubric, score_round, weighted_score


def verdict_round(valid_verdict) -> Round:
    return Round(index=1, kind="verdict", report=VerdictReport.model_validate(valid_verdict))


def judge_reply(scores: dict[str, int]) -> str:
    return json.dumps(
        {"scores": [{"dimension": k, "evidence": "line", "score": v} for k, v in scores.items()]}
    )


def test_rubric_is_well_formed():
    rubric = load_rubric()
    ids = [d.id for d in rubric.dimensions]
    assert len(ids) == len(set(ids))
    for d in rubric.dimensions:
        assert d.weight > 0
        assert set(d.anchors) == {1, 3, 5}
        assert set(d.applies_to) <= {"questions", "reask", "verdict"}
    for kind in ("questions", "reask", "verdict"):
        assert rubric.for_kind(kind)


def test_weighted_score_spans_zero_to_hundred():
    dims = load_rubric().for_kind("verdict")
    assert weighted_score({d.id: 1 for d in dims}, dims) == 0
    assert weighted_score({d.id: 5 for d in dims}, dims) == 100
    assert weighted_score({d.id: 3 for d in dims}, dims) == 50


def test_heavier_dimensions_count_more():
    dims = load_rubric().for_kind("verdict")
    heavy = max(dims, key=lambda d: d.weight)
    light = min(dims, key=lambda d: d.weight)
    base = {d.id: 3 for d in dims}
    assert weighted_score({**base, heavy.id: 5}, dims) > weighted_score({**base, light.id: 5}, dims)


def test_judge_scores_a_verdict_on_the_judge_model(fake_anthropic, valid_verdict):
    dims = load_rubric().for_kind("verdict")
    client = fake_anthropic(judge_reply({d.id: 4 for d in dims}))
    settings = Settings()

    result = score_round(
        verdict_round(valid_verdict),
        idea="An idea",
        answers="1. Answers",
        settings=settings,
        client=client,
    )

    call = client.messages.calls[0]
    assert call["model"] == settings.judge_model
    assert "tools" not in call
    assert "[ANSWERS]" in call["messages"][0]["content"]
    assert result.passed
    assert result.score == 75


def test_a_dimension_below_the_floor_fails_the_case(fake_anthropic, valid_verdict):
    dims = load_rubric().for_kind("verdict")
    scores = {d.id: 5 for d in dims} | {"validation_plan_quality": 2}
    result = score_round(
        verdict_round(valid_verdict),
        idea="An idea",
        answers="",
        settings=Settings(),
        client=fake_anthropic(judge_reply(scores)),
    )
    assert result.below_floor == ["validation_plan_quality"]
    assert not result.passed


def test_a_skipped_dimension_fails_rather_than_passing_silently(fake_anthropic, valid_verdict):
    dims = load_rubric().for_kind("verdict")
    scores = {d.id: 5 for d in dims[1:]}
    result = score_round(
        verdict_round(valid_verdict),
        idea="An idea",
        answers="",
        settings=Settings(),
        client=fake_anthropic(judge_reply(scores)),
    )
    assert result.missing == [dims[0].id]
    assert not result.passed


def test_question_rounds_get_question_dimensions_only(fake_anthropic, valid_question_set):
    round_ = Round(
        index=0,
        kind="questions",
        submission=[FounderMessage(text="idea")],
        questions=QuestionSet.model_validate(valid_question_set),
    )
    dims = load_rubric().for_kind("questions")
    client = fake_anthropic(judge_reply({d.id: 3 for d in dims}))
    result = score_round(
        round_, idea="An idea", answers="ignored", settings=Settings(), client=client
    )

    assert set(result.scores) == {d.id for d in dims}
    assert "validation_plan_quality" not in client.messages.calls[0]["system"][1]["text"]
    assert "[ANSWERS]" not in client.messages.calls[0]["messages"][0]["content"]
