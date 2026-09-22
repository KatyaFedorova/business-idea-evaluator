"""Run the graded eval suite against the real API and report pass rate and cost.

This spends money: each case runs one or two real rounds. Nothing here is imported
by the application; it exists to prove the prompt still behaves.
"""

from __future__ import annotations

import json
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
from evals import graders

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


def _run_case(case: dict, settings: Settings, client: Any) -> tuple[Round, float]:
    """Run the case to the round it is about, answering re-asks along the way.

    A case that is not about vagueness must reach a verdict: otherwise every
    structural grader fails with "no report on a reask round", which says nothing
    about the prompt and everything about the harness.
    """
    attachments = _case_attachments(case, client, settings)
    first = ask_questions(
        case["idea"], attachments=attachments, settings=settings, client=client
    )
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
        name, kwargs = (entry, {}) if isinstance(entry, str) else (
            entry["name"],
            {k: v for k, v in entry.items() if k != "name"},
        )
        grader = graders.STRUCTURAL.get(name)
        if grader is None:
            results.append(graders.GradeResult(name, False, "unknown grader"))
            continue
        results.append(grader(round_, **kwargs))
    return results


def main(
    cases_dir: str | None = None, as_json: bool = False, production: bool = False
) -> int:
    settings = eval_settings(production)
    if not settings.has_api_key:
        print("No ANTHROPIC_API_KEY set; the eval suite needs one.", file=sys.stderr)
        return 1

    client = build_client()
    cases = load_cases(Path(cases_dir) if cases_dir else CASES_DIR)
    report: list[dict] = []
    total_cost = 0.0

    for case in cases:
        try:
            round_, cost = _run_case(case, settings, client)
            results = _grade(case, round_)
            failures = [r for r in results if not r.passed]
        except BieError as exc:
            detail = f"{exc.message} [{exc.code}] {(exc.detail or '')[:400]}"
            results, failures, cost = [], [graders.GradeResult("run", False, detail)], 0.0
        total_cost += cost
        report.append(
            {
                "case": case["name"],
                "passed": not failures,
                "cost_usd": round(cost, 4),
                "failures": [{"grader": f.name, "detail": f.detail} for f in failures],
            }
        )
        if not as_json:
            mark = "PASS" if not failures else "FAIL"
            print(f"[{mark}] {case['name']}  (${cost:.4f})")
            for failure in failures:
                print(f"        {failure.name}: {failure.detail}")

    passed = sum(1 for r in report if r["passed"])
    rate = passed / len(report) if report else 0.0
    if as_json:
        print(json.dumps({"cases": report, "pass_rate": rate, "total_cost_usd": total_cost}, indent=2))
    else:
        print(f"\n{passed}/{len(report)} passed ({rate:.0%}) · ${total_cost:.2f} total")
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
