"""Run the graded eval suite against the real API and report pass rate and cost.

This spends money: each case runs one or two real rounds. Nothing here is imported
by the application; it exists to prove the prompt still behaves.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from bie.attachments import prepare_files
from bie.claude import build_client
from bie.config import Settings
from bie.errors import BieError
from bie.evaluator import ask_questions, evaluate
from bie.schemas import FounderMessage, Round
from evals import baseline, cache, graders
from evals.rubric import RubricResult, load_rubric, score_round

CASES_DIR = Path(__file__).parent / "cases"


def eval_settings(production: bool = False) -> Settings:
    """Cheap by default: the suite checks format and behaviour, not deep judgement.

    Sonnet at medium effort with three searches costs roughly a third of a production
    round. Pass production=True for the gate that must hold before a prompt ships.
    """
    settings = Settings()
    if production:
        return settings
    return replace(
        settings,
        model=settings.eval_model,
        question_effort=settings.eval_effort,
        verdict_effort=settings.eval_effort,
        max_searches=settings.eval_max_searches,
    )


def load_cases(directory: Path) -> list[dict]:
    cases = []
    for path in sorted(directory.glob("*.yaml")):
        case = yaml.safe_load(path.read_text())
        case["path"] = str(path)
        cases.append(case)
    return cases


def _case_attachments(case: dict, client: Any, settings: Settings) -> list:
    paths = [CASES_DIR / p for p in case.get("attachments", [])]
    return prepare_files(paths, client=client, settings=settings) if paths else []


def case_settings(case: dict, settings: Settings, production: bool) -> Settings:
    """A case may ask for fewer searches when none of its graders look at research.

    Ignored under --production: the gate that ships a prompt runs it as founders will.
    """
    if production or "max_searches" not in case:
        return settings
    return replace(settings, max_searches=int(case["max_searches"]))


def _round_one(
    case: dict, attachments: list, settings: Settings, client: Any, fresh: bool
) -> Round:
    """Round one, from disk when a verdict case only needs it as a stepping stone.

    The questions case always runs it live: round one is what it grades. Cases with
    attachments do too, because the cached round would carry stale attachment ids.
    """
    reusable = case.get("phase", "verdict") != "questions" and not attachments
    key = cache.round_one_key(case["idea"], settings)
    if reusable and not fresh and (cached := cache.load_round_one(key)) is not None:
        return cached.model_copy(update={"cost_usd": 0.0})
    first = ask_questions(case["idea"], attachments=attachments, settings=settings, client=client)
    if reusable:
        cache.save_round_one(key, first)
    return first


def _run_case(
    case: dict, settings: Settings, client: Any, *, fresh: bool = False
) -> tuple[Round, float]:
    """Run the case to the round it is about, answering re-asks along the way.

    A case that is not about vagueness must reach a verdict: otherwise every
    structural grader fails with "no report on a reask round", which says nothing
    about the prompt and everything about the harness.
    """
    attachments = _case_attachments(case, client, settings)
    first = _round_one(case, attachments, settings, client, fresh)
    spent = first.cost_usd
    if case.get("phase", "verdict") == "questions":
        return first, spent

    answers = case.get("answers", "")
    messages = [
        FounderMessage(text=a, attachment_ids=[a_.id for a_ in attachments])
        for a in ([answers] if isinstance(answers, str) else answers)
    ]
    rounds = [first]
    allow_reask = case.get("expect_reask", False)
    attempt_settings = settings if allow_reask else replace(settings, max_reasks=0)

    current = evaluate(
        case["idea"],
        rounds=rounds,
        answers=messages,
        attachments=attachments,
        settings=attempt_settings,
        client=client,
        spent=spent,
    )
    spent += current.cost_usd

    # One more turn if it still asked: the founder repeats what they already said,
    # and this time a verdict is required.
    if current.kind == "reask" and not allow_reask:
        rounds.append(current)
        current = evaluate(
            case["idea"],
            rounds=rounds,
            answers=messages,
            attachments=attachments,
            settings=replace(settings, max_reasks=0),
            client=client,
            spent=spent,
        )
        spent += current.cost_usd
    return current, spent


def _grade(case: dict, round_: Round) -> list[graders.GradeResult]:
    results = []
    for entry in case.get("graders", []):
        name, kwargs = (
            (entry, {})
            if isinstance(entry, str)
            else (
                entry["name"],
                {k: v for k, v in entry.items() if k != "name"},
            )
        )
        grader = graders.STRUCTURAL.get(name)
        if grader is None:
            results.append(graders.GradeResult(name, False, "unknown grader"))
            continue
        results.append(grader(round_, **kwargs))
    return results


def _answers_text(case: dict) -> str:
    answers = case.get("answers", "")
    return answers if isinstance(answers, str) else "\n\n".join(answers)


def _rubric_line(result: RubricResult) -> str:
    dims = "  ".join(f"{k}={v}" for k, v in result.scores.items())
    return f"        score {result.score:.0f}/100  {dims}"


def main(
    cases_dir: str | None = None,
    as_json: bool = False,
    production: bool = False,
    use_rubric: bool = True,
    only: list[str] | None = None,
    fresh: bool = False,
    save_baseline: bool = False,
) -> int:
    settings = eval_settings(production)
    if not settings.has_api_key:
        key = "GROQ_API_KEY" if settings.provider == "groq" else "ANTHROPIC_API_KEY"
        print(f"No {key} set; the eval suite needs one.", file=sys.stderr)
        return 1

    # Principle III: this suite spends real money, so it must not run unattended.
    # CI sets CI=true; a human at a terminal does not.
    if os.getenv("CI") and not os.getenv("BIE_EVAL_CONFIRMED"):
        print(
            "Refusing to run the eval suite in CI: it spends real money and needs the "
            "owner's permission for each run (constitution, Principle III). Set "
            "BIE_EVAL_CONFIRMED=1 to override deliberately.",
            file=sys.stderr,
        )
        return 2

    if save_baseline and only:
        print("A baseline is the whole suite: drop --case to save one.", file=sys.stderr)
        return 1

    client = build_client()
    cases = load_cases(Path(cases_dir) if cases_dir else CASES_DIR)
    if only:
        cases = [c for c in cases if any(o in c["name"] or o in Path(c["path"]).stem for o in only)]
        if not cases:
            print(f"No case matches {only}.", file=sys.stderr)
            return 1
    rubric = load_rubric() if use_rubric else None
    passed_before = {} if fresh else cache.load_results()
    passed_now: dict[str, dict] = dict(passed_before)
    report: list[dict] = []
    total_cost = 0.0
    dimension_scores: dict[str, list[int]] = {}

    for case in cases:
        run_settings = case_settings(case, settings, production)
        attachment_bytes = [(CASES_DIR / p).read_bytes() for p in case.get("attachments", [])]
        key = cache.case_key(case, attachment_bytes, run_settings, rubric is not None)
        previous = passed_before.get(case["path"])
        if previous and previous.get("key") == key:
            # Nothing that could change the answer has changed since it passed.
            entry = {**previous["entry"], "cost_usd": 0.0, "cached": True}
            report.append(entry)
            for name, value in entry["dimensions"].items():
                dimension_scores.setdefault(name, []).append(value)
            if not as_json:
                print(f"[PASS] {case['name']}  (cached, $0)")
            continue

        scored: RubricResult | None = None
        try:
            round_, cost = _run_case(case, run_settings, client, fresh=fresh)
            results = _grade(case, round_)
            failures = [r for r in results if not r.passed]
        except BieError as exc:
            detail = f"{exc.message} [{exc.code}] {(exc.detail or '')[:400]}"
            round_, results, cost = None, [], 0.0
            failures = [graders.GradeResult("run", False, detail)]
        if round_ is not None and rubric is not None and case.get("rubric", True):
            try:
                scored = score_round(
                    round_,
                    idea=case["idea"],
                    answers=_answers_text(case),
                    settings=run_settings,
                    client=client,
                    rubric=rubric,
                )
            except BieError as exc:
                # A judge failure is not a prompt failure: say so, keep the structural grades.
                failures.append(
                    graders.GradeResult("rubric", False, f"judge failed: {exc.message}")
                )
        if scored is not None:
            cost += scored.cost_usd
            for name in scored.below_floor:
                failures.append(
                    graders.GradeResult(
                        f"rubric:{name}", False, f"{scored.scores[name]}/5: {scored.evidence[name]}"
                    )
                )
            if scored.missing:
                failures.append(
                    graders.GradeResult("rubric", False, f"judge skipped {scored.missing}")
                )
            for name, value in scored.scores.items():
                dimension_scores.setdefault(name, []).append(value)
        total_cost += cost
        entry = {
            "case": case["name"],
            "passed": not failures,
            "cost_usd": round(cost, 4),
            "score": scored.score if scored else None,
            "dimensions": scored.scores if scored else {},
            "failures": [{"grader": f.name, "detail": f.detail} for f in failures],
        }
        report.append(entry)
        # Only passes are remembered: a failure must be rerun to be believed fixed.
        if failures:
            passed_now.pop(case["path"], None)
        else:
            passed_now[case["path"]] = {"key": key, "entry": entry}
        cache.save_results(passed_now)
        if not as_json:
            mark = "PASS" if not failures else "FAIL"
            print(f"[{mark}] {case['name']}  (${cost:.4f})")
            if scored is not None:
                print(_rubric_line(scored))
            for failure in failures:
                print(f"        {failure.name}: {failure.detail}")

    passed = sum(1 for r in report if r["passed"])
    rate = passed / len(report) if report else 0.0
    case_scores = [r["score"] for r in report if r["score"] is not None]
    mean_score = round(sum(case_scores) / len(case_scores), 1) if case_scores else None
    dimension_means = {k: round(sum(v) / len(v), 2) for k, v in sorted(dimension_scores.items())}
    summary = {
        "cases": report,
        "pass_rate": rate,
        "mean_score": mean_score,
        "dimension_means": dimension_means,
        "total_cost_usd": total_cost,
    }
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"\n{passed}/{len(report)} passed ({rate:.0%}) · ${total_cost:.2f} total")
        if mean_score is not None:
            print(f"Quality score: {mean_score:.0f}/100")
            for name, mean in dimension_means.items():
                print(f"  {name:<26} {mean:.2f}/5")

    if save_baseline:
        baseline.save(summary, settings)
        print(f"\nBaseline saved to {baseline.BASELINE_PATH.name}.", file=sys.stderr)
        return 0

    saved = baseline.load()
    if saved is None:
        return 0 if passed == len(report) else 1

    # Against a baseline, the question is "did it get worse", not "is it perfect":
    # a case that already failed in the baseline is known, not new.
    comparison = baseline.compare(summary, saved, settings, partial=bool(only))
    out = sys.stderr if as_json else sys.stdout
    print(f"\nAgainst the baseline of {saved['saved_at']}:", file=out)
    for warning in comparison.warnings:
        print(f"  ! {warning}", file=out)
    for line in comparison.lines:
        print(f"  {line}", file=out)
    if comparison.regressions:
        print("REGRESSIONS:", file=out)
        for regression in comparison.regressions:
            print(f"  ✗ {regression}", file=out)
        return 1
    print("No regressions.", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
