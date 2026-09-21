"""Runtime configuration, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Effort levels accepted by output_config.effort on current Claude models.
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Settings:
    """Everything the app reads from the environment, in one place."""

    model: str = field(default_factory=lambda: os.getenv("BIE_MODEL", "claude-opus-5"))
    judge_model: str = field(
        default_factory=lambda: os.getenv("BIE_JUDGE_MODEL", "claude-sonnet-5")
    )
    effort: str = field(default_factory=lambda: os.getenv("BIE_EFFORT", "medium"))
    prompt_version: str = field(default_factory=lambda: os.getenv("BIE_PROMPT_VERSION", "v2"))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("BIE_MAX_TOKENS", "8000")))
    concurrency: int = field(default_factory=lambda: int(os.getenv("BIE_CONCURRENCY", "4")))

    def __post_init__(self) -> None:
        if self.effort not in EFFORTS:
            raise ValueError(f"BIE_EFFORT must be one of {EFFORTS}, got {self.effort!r}")

    @property
    def has_api_key(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


settings = Settings()
