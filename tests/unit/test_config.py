"""T005 — Settings holds every knob, and rejects nonsense at construction."""

from __future__ import annotations

import pytest

from bie.config import EFFORTS, Settings


def test_defaults():
    s = Settings()
    assert s.model == "claude-opus-5"
    assert s.prompt_version == "v3"
    assert s.question_effort == "medium"
    assert s.verdict_effort == "high"
    assert s.min_idea_chars == 40
    assert s.max_attachments == 5
    assert s.max_attachment_mb == 10
    assert s.max_searches == 8
    assert s.max_cost_per_round_usd == 1.50
    assert s.max_cost_per_session_usd == 5.00
    assert s.max_cost_per_day_usd == 2.00
    assert s.max_reasks == 3


@pytest.mark.parametrize(
    ("env", "attr", "raw", "expected"),
    [
        ("BIE_MODEL", "model", "claude-sonnet-5", "claude-sonnet-5"),
        ("BIE_PROMPT_VERSION", "prompt_version", "v4", "v4"),
        ("BIE_QUESTION_EFFORT", "question_effort", "low", "low"),
        ("BIE_VERDICT_EFFORT", "verdict_effort", "max", "max"),
        ("BIE_MIN_IDEA_CHARS", "min_idea_chars", "10", 10),
        ("BIE_MAX_ATTACHMENTS", "max_attachments", "2", 2),
        ("BIE_MAX_ATTACHMENT_MB", "max_attachment_mb", "3", 3),
        ("BIE_MAX_SEARCHES", "max_searches", "20", 20),
        ("BIE_MAX_COST_PER_ROUND_USD", "max_cost_per_round_usd", "0.25", 0.25),
        ("BIE_MAX_COST_PER_SESSION_USD", "max_cost_per_session_usd", "9.5", 9.5),
        ("BIE_MAX_REASKS", "max_reasks", "1", 1),
    ],
)
def test_every_setting_is_env_overridable(monkeypatch, env, attr, raw, expected):
    monkeypatch.setenv(env, raw)
    assert getattr(Settings(), attr) == expected


@pytest.mark.parametrize("field", ["BIE_EFFORT", "BIE_QUESTION_EFFORT", "BIE_VERDICT_EFFORT"])
def test_invalid_effort_fails_at_construction(monkeypatch, field):
    monkeypatch.setenv(field, "turbo")
    with pytest.raises(ValueError) as exc:
        Settings()
    assert "turbo" in str(exc.value)
    assert str(EFFORTS[0]) in str(exc.value)


@pytest.mark.parametrize(
    "env",
    [
        "BIE_MAX_COST_PER_ROUND_USD",
        "BIE_MAX_COST_PER_SESSION_USD",
        "BIE_MAX_ATTACHMENTS",
        "BIE_MAX_ATTACHMENT_MB",
        "BIE_MIN_IDEA_CHARS",
    ],
)
def test_non_positive_limits_fail_at_construction(monkeypatch, env):
    monkeypatch.setenv(env, "0")
    with pytest.raises(ValueError):
        Settings()


def test_zero_searches_means_research_is_off_not_invalid():
    """A search budget of 0 is a deliberate switch, unlike a ceiling of 0."""
    import os

    os.environ["BIE_MAX_SEARCHES"] = "0"
    try:
        settings = Settings()
        assert settings.max_searches == 0
        assert settings.research_enabled is False
    finally:
        del os.environ["BIE_MAX_SEARCHES"]
    assert Settings().research_enabled is True


def test_attachment_bytes_is_derived():
    assert Settings().max_attachment_bytes == 10 * 1024 * 1024
