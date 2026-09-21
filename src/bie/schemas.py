"""The contract between Claude and the app.

Every model here is used twice: as the structured-output schema Claude must fill,
and as the type the API, the CLI and the graders read.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["pursue", "refine", "pivot", "drop"]
RiskSeverity = Literal["low", "medium", "high"]

DIMENSIONS = ("problem_severity", "market_size", "differentiation", "feasibility", "monetization")


class DimensionScore(BaseModel):
    """One scored axis, with the reasoning that produced the number."""

    name: Literal[
        "problem_severity", "market_size", "differentiation", "feasibility", "monetization"
    ]
    score: int = Field(ge=1, le=10)
    rationale: str = Field(min_length=1)


class Risk(BaseModel):
    title: str = Field(min_length=1)
    severity: RiskSeverity
    mitigation: str = Field(min_length=1)


class IdeaEvaluation(BaseModel):
    """The full verdict returned for one business idea."""

    headline: str = Field(min_length=1, description="One-line read on the idea.")
    verdict: Verdict
    overall_score: int = Field(ge=1, le=100)
    dimensions: list[DimensionScore] = Field(min_length=5, max_length=5)
    target_customer: str
    riskiest_assumption: str
    risks: list[Risk] = Field(min_length=1, max_length=5)
    first_experiment: str = Field(description="The cheapest test that could falsify the idea.")
    comparable_companies: list[str] = Field(max_length=5)


class Usage(BaseModel):
    """What one Claude call consumed."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0


class EvaluationResult(BaseModel):
    """An evaluation plus the telemetry of the call that produced it."""

    idea: str
    prompt_version: str
    evaluation: IdeaEvaluation
    usage: Usage


class JudgeVerdict(BaseModel):
    """Output of the LLM-as-judge grader."""

    passed: bool
    score: int = Field(ge=1, le=5, description="1 = unusable, 5 = excellent.")
    reasoning: str
