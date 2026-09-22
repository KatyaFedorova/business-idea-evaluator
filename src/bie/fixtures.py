"""Record a real API response once, replay it from disk for free.

Diagnosing a failure meant re-sending the same request until it failed again, which is
how $0.20 went on seven identical calls. With BIE_RECORD=1 the reply is written to disk;
with BIE_REPLAY pointing at that file, no call is made at all.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(os.getenv("BIE_FIXTURE_DIR", "tests/fixtures"))


class Replayed:
    """A recorded reply, wearing the shape the SDK response had."""

    def __init__(self, data: Any) -> None:
        self._data = data
        if isinstance(data, dict):
            for key, value in data.items():
                setattr(self, key, _wrap(value))

    def __repr__(self) -> str:
        return f"Replayed({self._data!r})"


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return Replayed(value)
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _plain(value: Any) -> Any:
    """Whatever the SDK gave us, as JSON-safe data."""
    for method in ("model_dump", "to_dict", "dict"):
        if hasattr(value, method):
            try:
                return _plain(getattr(value, method)())
            except Exception:  # noqa: BLE001,S112 - try the next shape instead
                continue
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {
            k: _plain(v) for k, v in vars(value).items() if not k.startswith("_")
        }
    return str(value)


def recording_enabled() -> bool:
    return os.getenv("BIE_RECORD", "").strip() not in ("", "0", "false", "False")


def replay_path() -> Path | None:
    raw = os.getenv("BIE_REPLAY", "").strip()
    return Path(raw) if raw else None


def record(message: Any, *, label: str = "reply") -> Path:
    """Write one reply to disk and return where it landed."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = FIXTURE_DIR / f"{label}-{stamp}.json"
    path.write_text(json.dumps(_plain(message), indent=2, default=str))
    return path


def load(path: Path) -> Replayed:
    return Replayed(json.loads(Path(path).read_text()))
