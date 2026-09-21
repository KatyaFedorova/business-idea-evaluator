"""Versioned prompt assets, loaded from disk so a prompt change is a content change."""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent
_FILES = {"v3": "v3_interrogator.md"}


class UnknownPromptVersion(ValueError):
    """Asked for a prompt version that does not exist on disk."""


def available_versions() -> tuple[str, ...]:
    return tuple(sorted(_FILES))


def load(version: str) -> str:
    """Return the prompt text for `version`, or raise UnknownPromptVersion."""
    try:
        name = _FILES[version]
    except KeyError:
        raise UnknownPromptVersion(
            f"no prompt for version {version!r}; have {available_versions()}"
        ) from None
    return (_DIR / name).read_text(encoding="utf-8")
