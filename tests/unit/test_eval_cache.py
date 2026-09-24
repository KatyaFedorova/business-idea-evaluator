"""The eval suite does not pay twice for the same answer. No network."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bie.config import Settings
from bie.schemas import FounderMessage, QuestionSet, Round, VerdictReport
from evals import cache, run


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(cache, "RESULTS_PATH", tmp_path / ".cache" / "results.json")
    from evals import baseline

    monkeypatch.setattr(baseline, "BASELINE_PATH", tmp_path / "baseline.json")


@pytest.fixture
def case_file(tmp_path) -> dict:
    path = tmp_path / "case.yaml"
    path.write_text("name: a case\nphase: verdict\nidea: An idea long enough to pass.\n")
    return {"name": "a case", "phase": "verdict", "idea": "An idea long enough.", "path": str(path)}


def questions_round(valid_question_set) -> Round:
    return Round(
        index=0,
        kind="questions",
        submission=[FounderMessage(text="idea")],
        questions=QuestionSet.model_validate(valid_question_set),
        cost_usd=0.05,
    )


def test_case_search_limit_applies_except_in_production():
    settings = Settings()
    assert run.case_settings({"max_searches": 0}, settings, production=False).max_searches == 0
    assert run.case_settings({"max_searches": 0}, settings, production=True) is settings
    assert run.case_settings({}, settings, production=False) is settings


def test_round_one_key_tracks_what_changes_the_answer():
    settings = Settings()
    key = cache.round_one_key("idea", settings)
    assert key == cache.round_one_key("idea ", settings)
    assert key != cache.round_one_key("another idea", settings)
    assert key != cache.round_one_key("idea", replace(settings, model="claude-haiku-4-5"))


def test_case_key_changes_with_the_case_file_and_settings(case_file):
    settings = Settings()
    key = cache.case_key(case_file, [], settings, rubric=True)
    assert key != cache.case_key(case_file, [], settings, rubric=False)
    assert key != cache.case_key(case_file, [], replace(settings, max_searches=0), rubric=True)
    Path(case_file["path"]).write_text("name: a case\nidea: edited\n")
    assert key != cache.case_key(case_file, [], settings, rubric=True)


def test_verdict_cases_reuse_round_one(monkeypatch, case_file, valid_question_set):
    calls = []

    def fake_ask(idea, **kw):
        calls.append(idea)
        return questions_round(valid_question_set)

    monkeypatch.setattr(run, "ask_questions", fake_ask)
    settings = Settings()
    first = run._round_one(case_file, [], settings, client=None, fresh=False)
    again = run._round_one(case_file, [], settings, client=None, fresh=False)

    assert len(calls) == 1
    assert first.cost_usd == 0.05
    assert again.cost_usd == 0.0  # already paid for
    run._round_one(case_file, [], settings, client=None, fresh=True)
    assert len(calls) == 2


def test_the_questions_case_always_runs_round_one_live(monkeypatch, case_file, valid_question_set):
    calls = []
    monkeypatch.setattr(
        run,
        "ask_questions",
        lambda idea, **kw: calls.append(idea) or questions_round(valid_question_set),
    )
    case = {**case_file, "phase": "questions"}
    run._round_one(case, [], Settings(), client=None, fresh=False)
    run._round_one(case, [], Settings(), client=None, fresh=False)
    assert len(calls) == 2


def _suite(tmp_path, monkeypatch, verdict: dict) -> list[str]:
    """A one-case suite whose case run is faked; returns the names of cases actually run."""
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "one.yaml").write_text(
        "name: one\nphase: verdict\nidea: An idea long enough to pass.\ngraders:\n"
        "  - report_structure\n"
    )
    ran = []

    def fake_run_case(case, settings, client, *, fresh=False):
        ran.append(case["name"])
        return Round(index=1, kind="verdict", report=VerdictReport.model_validate(verdict)), 0.1

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(run, "build_client", lambda: None)
    monkeypatch.setattr(run, "_run_case", fake_run_case)
    return ran


def test_an_unchanged_passing_case_is_not_rerun(tmp_path, monkeypatch, valid_verdict):
    ran = _suite(tmp_path, monkeypatch, valid_verdict)
    cases_dir = str(tmp_path / "cases")

    assert run.main(cases_dir=cases_dir, use_rubric=False) == 0
    assert run.main(cases_dir=cases_dir, use_rubric=False) == 0
    assert ran == ["one"]

    assert run.main(cases_dir=cases_dir, use_rubric=False, fresh=True) == 0
    assert ran == ["one", "one"]


def test_a_failing_case_is_always_rerun(tmp_path, monkeypatch, valid_verdict):
    ran = _suite(tmp_path, monkeypatch, valid_verdict)
    cases_dir = str(tmp_path / "cases")
    (tmp_path / "cases" / "one.yaml").write_text(
        "name: one\nphase: verdict\nidea: An idea long enough to pass.\ngraders:\n"
        "  - name: verdict_not_forced\n    forbidden: DONT_PROCEED\n"
    )

    assert run.main(cases_dir=cases_dir, use_rubric=False) == 1
    assert run.main(cases_dir=cases_dir, use_rubric=False) == 1
    assert ran == ["one", "one"]


def test_case_filter(tmp_path, monkeypatch, valid_verdict):
    ran = _suite(tmp_path, monkeypatch, valid_verdict)
    cases_dir = str(tmp_path / "cases")
    assert run.main(cases_dir=cases_dir, use_rubric=False, only=["nomatch"]) == 1
    assert ran == []


def test_baseline_catches_a_newly_failing_case_and_a_big_drop(tmp_path):
    from evals import baseline

    settings = Settings()
    before = {
        "cases": [
            {"case": "a", "passed": True, "score": 80.0, "dimensions": {}},
            {"case": "b", "passed": True, "score": 80.0, "dimensions": {}},
            {"case": "c", "passed": False, "score": 40.0, "dimensions": {}},
        ],
        "pass_rate": 2 / 3,
        "mean_score": 66.7,
        "dimension_means": {},
    }
    baseline.save(before, settings, path=tmp_path / "b.json")
    saved = baseline.load(tmp_path / "b.json")

    after = {
        **before,
        "cases": [
            {"case": "a", "passed": False, "score": 78.0, "dimensions": {}},  # newly failing
            {"case": "b", "passed": True, "score": 65.0, "dimensions": {}},  # dropped 15
            {"case": "c", "passed": False, "score": 38.0, "dimensions": {}},  # already failing
        ],
    }
    result = baseline.compare(after, saved, settings)
    assert len(result.regressions) == 2
    assert any(r.startswith("a:") for r in result.regressions)
    assert any(r.startswith("b:") for r in result.regressions)

    steady = {**before, "cases": [{**c, "score": c["score"] - 5} for c in before["cases"]]}
    assert not baseline.compare(steady, saved, settings).regressions  # noise, not change
