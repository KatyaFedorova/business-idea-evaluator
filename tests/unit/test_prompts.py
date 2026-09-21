"""T015 — the owner's prompt is loaded from disk, versioned, never inlined."""

from __future__ import annotations

import pytest

from bie.prompts import UnknownPromptVersion, available_versions, load


def test_v3_is_available():
    assert "v3" in available_versions()


def test_unknown_version_raises():
    with pytest.raises(UnknownPromptVersion):
        load("v99")


def test_prompt_keeps_the_owners_structure():
    text = load("v3")
    assert "STEP 1" in text and "STEP 2" in text
    assert "skeptical early-stage investor" in text
    for phrase in [
        "Do not evaluate yet",
        "PROCEED",
        "DON'T PROCEED",
        "VALIDATION PLAN",
        "Kill criteria",
        "No pep talk",
        "Label guesses",
    ]:
        assert phrase in text, phrase


def test_prompt_hardens_against_injection():
    text = load("v3").lower()
    assert "data to be evaluated" in text
    assert "instructions" in text
