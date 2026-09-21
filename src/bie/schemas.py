"""The contract between Claude and the app.

Every model here is used twice: as the structured-output schema Claude must fill,
and as the type the API, the CLI and the graders read. Nothing reaches a caller
without validating against one of them.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RoundKind = Literal["questions", "reask", "verdict"]
Confidence = Literal["low", "medium", "high"]
VerdictKind = Literal["PROCEED", "PROCEED_ONLY_AFTER_TESTING", "DONT_PROCEED"]
ResearchStatus = Literal["ok", "degraded", "unavailable"]
AttachmentKind = Literal["image", "pdf", "sheet", "text"]
QuestionTopic = Literal[
    "customer",
    "alternative",
    "willingness_to_pay",
    "unfair_advantage",
    "resources",
    "distribution",
    "falsification",
    "other",
]

# Step 1 must not evaluate. These are the shapes a verdict actually takes; the bare
# lowercase verb ("how would you proceed?") is deliberately not one of them.
_VERDICT_PATTERNS = (
    re.compile(r"\bverdict\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+proceed\b", re.IGNORECASE),
    re.compile(r"\bproceed\s+only\s+after\b", re.IGNORECASE),
    re.compile(r"\bPROCEED\b"),
)

# The prompt targets ~600 words and the eval suite holds the line at 700. This is the
# runaway stop, not the style rule: rejecting a 760-word report would show the founder an
# error instead of a perfectly good verdict.
WORD_LIMIT = 900


def _words(value: object) -> int:
    if isinstance(value, str):
        return len(value.split())
    if isinstance(value, BaseModel):
        return sum(_words(v) for v in value.__dict__.values())
    if isinstance(value, (list, tuple)):
        return sum(_words(v) for v in value)
    return 0


class Question(BaseModel):
    number: int = Field(ge=1)
    text: str = Field(min_length=1)
    topic: QuestionTopic


class QuestionSet(BaseModel):
    """Step 1: the questions whose answers would most change the verdict."""

    questions: list[Question] = Field(min_length=3, max_length=10)
    note: str | None = Field(
        default=None, description="Only on a re-ask: what was vague about the last answer."
    )

    @model_validator(mode="after")
    def _numbers_are_contiguous(self) -> QuestionSet:
        numbers = [q.number for q in self.questions]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"question numbers must be contiguous from 1, got {numbers}")
        return self

    @model_validator(mode="after")
    def _no_verdict_in_step_one(self) -> QuestionSet:
        for question in self.questions:
            for pattern in _VERDICT_PATTERNS:
                if pattern.search(question.text):
                    raise ValueError(
                        f"question {question.number} reads like a verdict, which step 1 "
                        f"must not contain: {question.text!r}"
                    )
        return self


class ReAsk(QuestionSet):
    """A QuestionSet that must say what was vague (FR-006)."""

    @model_validator(mode="after")
    def _note_is_required(self) -> ReAsk:
        if not (self.note or "").strip():
            raise ValueError("a re-ask must carry a note naming what was vague")
        return self


class FailureMode(BaseModel):
    rank: int = Field(ge=1, le=3, description="1 is the most likely to kill the idea.")
    text: str = Field(min_length=1)
    is_guess: bool = Field(description="True when this is inference rather than known fact.")


class ValidationPlan(BaseModel):
    assumption_tested: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1, max_length=8)
    who_to_talk_to: str = Field(min_length=1)
    pass_threshold: str = Field(min_length=1)
    fail_threshold: str = Field(min_length=1)
    duration_days: int = Field(ge=1, le=14, description="Under two weeks.")
    requires_code: bool = Field(description="Must be false: the test is a no-code test.")

    @model_validator(mode="after")
    def _no_code(self) -> ValidationPlan:
        if self.requires_code:
            raise ValueError("the validation plan must be doable with no code")
        return self


class ResearchDirection(BaseModel):
    question: str = Field(min_length=1)
    where_to_look: str = Field(min_length=1)
    competitor: str | None = None
    what_to_check: str | None = None


class VerdictReport(BaseModel):
    """Step 2: the verdict, exactly as the owner's prompt specifies it."""

    verdict: VerdictKind
    verdict_condition: str | None = Field(
        default=None, description="The X in PROCEED ONLY AFTER TESTING X. Null for other verdicts."
    )
    confidence: Confidence
    confidence_movers: str = Field(min_length=1)
    works_because: list[str] = Field(min_length=3, max_length=3)
    fails_because: list[FailureMode] = Field(min_length=3, max_length=3)
    riskiest_assumption: str = Field(min_length=1)
    validation_plan: ValidationPlan
    research_directions: list[ResearchDirection] = Field(min_length=1, max_length=6)
    kill_criteria: list[str] = Field(min_length=1, max_length=5)
    contradictions: list[str] = Field(default_factory=list, max_length=5)
    prior_art: list[str] = Field(default_factory=list, max_length=5)
    missing_data: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _condition_matches_verdict(self) -> VerdictReport:
        has_condition = bool((self.verdict_condition or "").strip())
        if self.verdict == "PROCEED_ONLY_AFTER_TESTING" and not has_condition:
            raise ValueError("verdict_condition is required for PROCEED_ONLY_AFTER_TESTING")
        if self.verdict != "PROCEED_ONLY_AFTER_TESTING" and has_condition:
            raise ValueError(f"verdict_condition must be null for verdict {self.verdict}")
        return self

    @model_validator(mode="after")
    def _failures_are_ranked_once_each(self) -> VerdictReport:
        ranks = [f.rank for f in self.fails_because]
        if sorted(ranks) != [1, 2, 3]:
            raise ValueError(f"fails_because must carry rank 1, 2 and 3 exactly once, got {ranks}")
        return self

    @model_validator(mode="after")
    def _stays_short(self) -> VerdictReport:
        if self.word_count > WORD_LIMIT:
            raise ValueError(
                f"the report runs to {self.word_count} words, past the {WORD_LIMIT}-word limit"
            )
        return self

    @property
    def word_count(self) -> int:
        return sum(_words(v) for v in self.__dict__.values())


class RoundDecision(BaseModel):
    """Step two returns one of two things, and says which (FR-006).

    The client branches on `decision` alone, never on the shape of the payload.
    """

    decision: Literal["reask", "verdict"]
    reask: ReAsk | None = Field(
        default=None, description="Set only when decision is reask: the questions to ask again."
    )
    report: VerdictReport | None = Field(
        default=None, description="Set only when decision is verdict."
    )

    @model_validator(mode="after")
    def _carries_what_it_claims(self) -> RoundDecision:
        if self.decision == "reask":
            if self.reask is None:
                raise ValueError("decision is reask but no reask questions were given")
            if self.report is not None:
                raise ValueError("a reask must not carry a report")
        else:
            if self.report is None:
                raise ValueError("decision is verdict but no report was given")
            if self.reask is not None:
                raise ValueError("a verdict must not carry reask questions")
        return self


class Source(BaseModel):
    """Where a claim came from. Extracted from search results, never model-authored."""

    url: str
    title: str = ""
    accessed_at: datetime | None = None


class Attachment(BaseModel):
    id: str
    filename: str
    kind: AttachmentKind
    size_bytes: int = Field(ge=0)
    file_id: str | None = None
    text: str | None = None
    readable: bool = True
    error: str | None = None


class FounderMessage(BaseModel):
    """One thing the founder said. A round may carry several (FR-033)."""

    text: str = ""
    attachment_ids: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    """What one Claude call consumed."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0


class Round(BaseModel):
    """One exchange: what the founder said, and what came back."""

    index: int = Field(ge=0)
    kind: RoundKind
    submitted_at: datetime | None = None
    submission: list[FounderMessage] = Field(default_factory=list)
    questions: QuestionSet | None = None
    report: VerdictReport | None = None
    sources: list[Source] = Field(default_factory=list)
    research_status: ResearchStatus = "unavailable"
    usage: Usage | None = None
    cost_usd: float = 0.0


class IdeaRevision(BaseModel):
    """A change to the idea box after the conversation started (FR-034)."""

    at: datetime | None = None
    previous: str
    current: str


class JudgeVerdict(BaseModel):
    """Output of the LLM-as-judge grader."""

    passed: bool
    score: int = Field(ge=1, le=5, description="1 = unusable, 5 = excellent.")
    reasoning: str
