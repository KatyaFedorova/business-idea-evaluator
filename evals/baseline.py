"""A saved run to measure every later run against.

`bie eval run --save-baseline` writes baseline.json. Every run after that is compared
with it, case by case and dimension by dimension. A regression is a case that passed in
the baseline and fails now, or whose score fell by more than REGRESSION_POINTS: model
output varies run to run, so a few points either way is noise, not a change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bie.config import Settings

BASELINE_PATH = Path(__file__).parent / "baseline.json"
REGRESSION_POINTS = 10.0


def save(summary: dict, settings: Settings, path: Path | None = None) -> None:
    path = path or BASELINE_PATH
    baseline = {
        "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": settings.provider,
        "model": settings.model,
        "judge_model": settings.judge_model,
        "prompt_version": settings.prompt_version,
        "pass_rate": summary["pass_rate"],
        "mean_score": summary["mean_score"],
        "dimension_means": summary["dimension_means"],
        "cases": {
            c["case"]: {"passed": c["passed"], "score": c["score"], "dimensions": c["dimensions"]}
            for c in summary["cases"]
        },
    }
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")


def load(path: Path | None = None) -> dict | None:
    path = path or BASELINE_PATH
    if not path.exists():
        return None
    return json.loads(path.read_text())


@dataclass
class Comparison:
    lines: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _delta(before: float | None, after: float | None, unit: str = "") -> str:
    if before is None or after is None:
        return f"{before} → {after}"
    diff = after - before
    arrow = "▲" if diff > 0 else "▼" if diff < 0 else "="
    return f"{before:g}{unit} → {after:g}{unit}  {arrow} {diff:+.1f}"


def compare(
    summary: dict, baseline: dict, settings: Settings, *, partial: bool = False
) -> Comparison:
    """partial: only some cases ran (--case), so suite-wide averages are not comparable."""
    result = Comparison()
    for name, value in (("model", settings.model), ("prompt_version", settings.prompt_version)):
        if baseline.get(name) != value:
            result.warnings.append(
                f"baseline {name} was {baseline.get(name)!r}, this run is {value!r}"
            )

    if not partial:
        before_rate = round(baseline["pass_rate"] * 100)
        now_rate = round(summary["pass_rate"] * 100)
        result.lines.append(
            f"overall score   {_delta(baseline.get('mean_score'), summary['mean_score'])}"
        )
        result.lines.append(f"pass rate       {_delta(before_rate, now_rate, '%')}")
        for name, now in summary["dimension_means"].items():
            before = baseline.get("dimension_means", {}).get(name)
            result.lines.append(f"  {name:<26} {_delta(before, now)}")

    for case in summary["cases"]:
        before = baseline["cases"].get(case["case"])
        if before is None:
            result.lines.append(f"  new case: {case['case']}")
            continue
        result.lines.append(f"  {case['case']:<52} {_delta(before['score'], case['score'])}")
        if before["passed"] and not case["passed"]:
            result.regressions.append(f"{case['case']}: passed in the baseline, fails now")
        elif (
            before["score"] is not None
            and case["score"] is not None
            and before["score"] - case["score"] > REGRESSION_POINTS
        ):
            result.regressions.append(
                f"{case['case']}: score {before['score']:g} → {case['score']:g}"
            )
    return result
