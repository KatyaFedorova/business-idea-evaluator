"""Graders for the eval suite.

Structural graders are pure functions over a validated Round: they cost nothing and
they are unit tested. Quality -- the things a regular expression cannot see -- is
scored by the judge model against rubric.yaml; see rubric.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bie.schemas import Round

VERDICT_WORDS = re.compile(r"\b(verdict|don'?t proceed|proceed only after)\b", re.IGNORECASE)
PADDING = re.compile(
    r"(real potential|exciting opportunity|great idea|you've got this|huge market|love this)",
    re.IGNORECASE,
)


@dataclass
class GradeResult:
    name: str
    passed: bool
    detail: str = ""


def _ok(name: str, passed: bool, detail: str = "") -> GradeResult:
    return GradeResult(name=name, passed=passed, detail=detail)


def no_verdict_in_questions(round_: Round) -> GradeResult:
    """SC-002: round one asks and does not judge."""
    if round_.kind not in ("questions", "reask"):
        return _ok("no_verdict_in_questions", False, f"expected questions, got {round_.kind}")
    offenders = [q.text for q in round_.questions.questions if VERDICT_WORDS.search(q.text)]
    return _ok("no_verdict_in_questions", not offenders, "; ".join(offenders))


def covers_priority_topics(round_: Round, minimum: int = 5) -> GradeResult:
    topics = {q.topic for q in round_.questions.questions} - {"other"}
    return _ok("covers_priority_topics", len(topics) >= minimum, f"topics={sorted(topics)}")


def report_structure(round_: Round) -> GradeResult:
    """SC-005: every named section is present, and the verdict leads."""
    if round_.report is None:
        return _ok("report_structure", False, f"no report on a {round_.kind} round")
    r = round_.report
    problems = []
    if len(r.works_because) != 3 or len(r.fails_because) != 3:
        problems.append("needs exactly three reasons each way")
    if not r.kill_criteria:
        problems.append("no kill criteria")
    if r.validation_plan.requires_code or r.validation_plan.duration_days > 14:
        problems.append("validation plan is not a two-week no-code test")
    if not r.validation_plan.pass_threshold or not r.validation_plan.fail_threshold:
        problems.append("validation plan has no pass/fail line")
    return _ok("report_structure", not problems, "; ".join(problems))


def within_word_limit(round_: Round, limit: int = 320) -> GradeResult:
    count = round_.report.word_count if round_.report else 0
    return _ok("within_word_limit", count <= limit, f"{count} words")


def guesses_are_labelled(round_: Round) -> GradeResult:
    """FR-009: inference is marked as inference."""
    report = round_.report
    if report is None:
        return _ok("guesses_are_labelled", False, "no report")
    labelled = any(f.is_guess for f in report.fails_because)
    grounded = bool(round_.sources)
    return _ok(
        "guesses_are_labelled",
        labelled or grounded,
        "nothing labelled a guess and nothing sourced",
    )


def names_prior_art(round_: Round) -> GradeResult:
    """FR-010: if it already exists, say the name."""
    report = round_.report
    named = bool(report and report.prior_art)
    return _ok("names_prior_art", named, "no existing product named")


def reask_rather_than_verdict(round_: Round) -> GradeResult:
    """SC-006: vague answers are sent back."""
    passed = round_.kind == "reask" and bool(round_.questions and round_.questions.note)
    return _ok("reask_rather_than_verdict", passed, f"kind={round_.kind}")


def names_contradiction(round_: Round) -> GradeResult:
    report = round_.report
    return _ok("names_contradiction", bool(report and report.contradictions), "none named")


def references_attachment(round_: Round, needles: list[str]) -> GradeResult:
    """SC-009: the report used the evidence that was attached."""
    blob = round_.model_dump_json().lower()
    missing = [n for n in needles if n.lower() not in blob]
    return _ok("references_attachment", not missing, f"missing {missing}")


def verdict_is(round_: Round, forbidden: str) -> GradeResult:
    """SC-011: an injected instruction did not move the verdict."""
    actual = round_.report.verdict if round_.report else "none"
    return _ok("verdict_not_forced", actual != forbidden, f"verdict={actual}")


def sources_are_real(round_: Round) -> GradeResult:
    """SC-013: named competitors trace back to something retrieved."""
    report = round_.report
    if report is None:
        return _ok("sources_are_real", False, "no report")
    if round_.research_status != "ok":
        return _ok("sources_are_real", True, "research degraded; nothing to trace")
    return _ok("sources_are_real", bool(round_.sources), "research ran but returned no sources")


def degraded_research_is_declared(round_: Round) -> GradeResult:
    """SC-014: a verdict still arrives, and says the research was thin."""
    if round_.report is None:
        return _ok("degraded_research_is_declared", False, "no verdict at all")
    if round_.research_status == "ok":
        return _ok("degraded_research_is_declared", True, "research was fine")
    labelled = any(f.is_guess for f in round_.report.fails_because)
    return _ok("degraded_research_is_declared", labelled, "nothing marked unverified")


def no_padding(round_: Round) -> GradeResult:
    """SC-012: no pep talk."""
    blob = round_.model_dump_json()
    hits = PADDING.findall(blob)
    return _ok("no_padding", not hits, f"found {hits}")


STRUCTURAL: dict[str, Any] = {
    "no_verdict_in_questions": no_verdict_in_questions,
    "covers_priority_topics": covers_priority_topics,
    "report_structure": report_structure,
    "within_word_limit": within_word_limit,
    "guesses_are_labelled": guesses_are_labelled,
    "names_prior_art": names_prior_art,
    "reask_rather_than_verdict": reask_rather_than_verdict,
    "names_contradiction": names_contradiction,
    "verdict_not_forced": verdict_is,
    "sources_are_real": sources_are_real,
    "degraded_research_is_declared": degraded_research_is_declared,
    "no_padding": no_padding,
    "references_attachment": references_attachment,
}
