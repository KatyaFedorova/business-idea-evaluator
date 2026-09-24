"""Runtime configuration, read once from the environment.

Every knob the application has lives here. Nothing anywhere else reads os.environ,
and nothing anywhere else hardcodes a model id, a limit or a ceiling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Effort levels accepted by output_config.effort on current Claude models.
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# Where the model runs. "groq" is a free open model; "anthropic" is Claude.
PROVIDERS = ("groq", "anthropic")

# What a founder may attach. Images and PDFs go to the model natively; sheets and
# text are converted to text first.
ALLOWED_MEDIA_TYPES: dict[str, str] = {
    "image/png": "image",
    "image/jpeg": "image",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "sheet",
    "text/csv": "sheet",
    "text/plain": "text",
    "text/markdown": "text",
}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Everything the app reads from the environment, in one place."""

    provider: str = field(default_factory=lambda: os.getenv("BIE_PROVIDER", "groq"))
    # The one open model used for everything when provider is groq: the evaluator, the
    # eval runs and the judge.
    groq_model: str = field(
        default_factory=lambda: os.getenv("BIE_GROQ_MODEL", "openai/gpt-oss-120b")
    )
    model: str = field(default_factory=lambda: os.getenv("BIE_MODEL", "claude-opus-5"))
    judge_model: str = field(
        default_factory=lambda: os.getenv("BIE_JUDGE_MODEL", "claude-sonnet-5")
    )
    effort: str = field(default_factory=lambda: os.getenv("BIE_EFFORT", "medium"))
    question_effort: str = field(
        default_factory=lambda: os.getenv("BIE_QUESTION_EFFORT", "medium")
    )
    verdict_effort: str = field(default_factory=lambda: os.getenv("BIE_VERDICT_EFFORT", "high"))
    prompt_version: str = field(default_factory=lambda: os.getenv("BIE_PROMPT_VERSION", "v3"))
    max_tokens: int = field(default_factory=lambda: _int("BIE_MAX_TOKENS", 8000))
    concurrency: int = field(default_factory=lambda: _int("BIE_CONCURRENCY", 4))

    # What a founder may submit.
    min_idea_chars: int = field(default_factory=lambda: _int("BIE_MIN_IDEA_CHARS", 40))
    max_attachments: int = field(default_factory=lambda: _int("BIE_MAX_ATTACHMENTS", 5))
    max_attachment_mb: int = field(default_factory=lambda: _int("BIE_MAX_ATTACHMENT_MB", 10))

    # Research and cost control.
    # 0 turns research off entirely: fast and cheap for iterating on the UI, but the
    # verdict then rests on recalled knowledge, which is what FR-013 exists to prevent.
    max_searches: int = field(default_factory=lambda: _int("BIE_MAX_SEARCHES", 8))
    max_cost_per_round_usd: float = field(
        default_factory=lambda: _float("BIE_MAX_COST_PER_ROUND_USD", 1.50)
    )
    max_cost_per_session_usd: float = field(
        default_factory=lambda: _float("BIE_MAX_COST_PER_SESSION_USD", 5.00)
    )
    max_cost_per_day_usd: float = field(
        default_factory=lambda: _float("BIE_MAX_COST_PER_DAY_USD", 2.00)
    )
    max_reasks: int = field(default_factory=lambda: _int("BIE_MAX_REASKS", 3))

    # The eval suite runs the whole flow several times over, so it gets its own,
    # cheaper settings. `bie eval run --production` ignores these and uses the
    # real ones, which is what must pass before a prompt change ships.
    eval_model: str = field(default_factory=lambda: os.getenv("BIE_EVAL_MODEL", "claude-sonnet-5"))
    eval_effort: str = field(default_factory=lambda: os.getenv("BIE_EVAL_EFFORT", "medium"))
    eval_max_searches: int = field(default_factory=lambda: _int("BIE_EVAL_MAX_SEARCHES", 3))

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"BIE_PROVIDER must be one of {PROVIDERS}, got {self.provider!r}")
        if self.provider == "groq":
            # Claude model ids mean nothing to Groq, and Groq has no web search tool.
            for name in ("model", "judge_model", "eval_model"):
                object.__setattr__(self, name, self.groq_model)
            object.__setattr__(self, "max_searches", 0)
            object.__setattr__(self, "eval_max_searches", 0)
        for name, value in (
            ("BIE_EFFORT", self.effort),
            ("BIE_QUESTION_EFFORT", self.question_effort),
            ("BIE_VERDICT_EFFORT", self.verdict_effort),
            ("BIE_EVAL_EFFORT", self.eval_effort),
        ):
            if value not in EFFORTS:
                raise ValueError(f"{name} must be one of {EFFORTS}, got {value!r}")
        for name, value in (
            ("BIE_MAX_TOKENS", self.max_tokens),
            ("BIE_MIN_IDEA_CHARS", self.min_idea_chars),
            ("BIE_MAX_ATTACHMENTS", self.max_attachments),
            ("BIE_MAX_ATTACHMENT_MB", self.max_attachment_mb),
            ("BIE_MAX_COST_PER_ROUND_USD", self.max_cost_per_round_usd),
            ("BIE_MAX_COST_PER_SESSION_USD", self.max_cost_per_session_usd),
            ("BIE_MAX_COST_PER_DAY_USD", self.max_cost_per_day_usd),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero, got {value!r}")
        for name, value in (
            ("BIE_MAX_REASKS", self.max_reasks),
            ("BIE_MAX_SEARCHES", self.max_searches),
            ("BIE_EVAL_MAX_SEARCHES", self.eval_max_searches),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative, got {value!r}")

    @property
    def research_enabled(self) -> bool:
        return self.max_searches > 0

    @property
    def max_attachment_bytes(self) -> int:
        return self.max_attachment_mb * 1024 * 1024

    @property
    def has_api_key(self) -> bool:
        if self.provider == "groq":
            return bool(os.getenv("GROQ_API_KEY"))
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


settings = Settings()
