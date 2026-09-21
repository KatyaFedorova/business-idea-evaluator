"""Run the graded eval suite against the real API and report pass rate and cost.

This spends money: each case runs one or two real rounds. Nothing here is imported
by the application; it exists to prove the prompt still behaves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from bie.claude import build_client
from bie.config import Settings
from bie.errors import BieError
from bie.evaluator import ask_questions, evaluate
from bie.schemas import FounderMessage, Round
from evals import graders

CASES_DIR = Path(__file__).parent / "cases"


def load_cases(directory: Path) -> list[dict]:
    cases = []
    for path in sorted(directory.glob("*.yaml")):
        case = yaml.safe_load(path.read_text())
        case["path"] = str(path)
        cases.append(case)
    return cases


def _run_case(case: dict, settings: Settings, client: Any) -> tuple[Round, float]:
    first = ask_questions(case["idea"], settings=settings, client=client)
    if case.get("phase", "verdict") == "questions":
        return first, first.cost_usd
    answers = case.get("answers", "")
    messages = [FounderMessage(text=a) for a in ([answers] if isinstance(answers, str) else answers)]
    second = evaluate(
        case["idea"],
        rounds=[first],
        answers=messages,
        settings=settings,
        client=client,
        spent=first.cost_usd,
    )
    return second, first.cost_usd + second.cost_usd


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


def main(cases_dir: str | None = None, as_json: bool = False) -> int:
    settings = Settings()
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
            results, failures, cost = [], [graders.GradeResult("run", False, exc.message)], 0.0
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
