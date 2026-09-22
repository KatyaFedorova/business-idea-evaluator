"""Fixtures shared by every test. Nothing here touches the network."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Self

import pytest


# --------------------------------------------------------------------------- #
# Fake Anthropic SDK objects
# --------------------------------------------------------------------------- #
@dataclass
class FakeServerToolUse:
    web_search_requests: int = 0


@dataclass
class FakeUsage:
    input_tokens: int = 1000
    output_tokens: int = 500
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    server_tool_use: FakeServerToolUse | None = None


@dataclass
class FakeBlock:
    type: str
    text: str | None = None
    content: Any = None


@dataclass
class FakeMessage:
    content: list[FakeBlock]
    usage: FakeUsage = field(default_factory=FakeUsage)
    model: str = "claude-opus-5"
    stop_reason: str = "end_turn"


def search_result_block(*results: tuple[str, str]) -> FakeBlock:
    """A successful web_search_tool_result block: content is a LIST."""
    return FakeBlock(
        type="web_search_tool_result",
        content=[
            FakeBlock(type="web_search_result", text=None, content=None).__class__(
                type="web_search_result"
            )
            if False
            else _Result(url=url, title=title)
            for url, title in results
        ],
    )


@dataclass
class _Result:
    url: str
    title: str
    type: str = "web_search_result"


@dataclass
class _SearchError:
    error_code: str
    type: str = "web_search_tool_result_error"


def search_error_block(error_code: str = "unavailable") -> FakeBlock:
    """A failed web_search_tool_result block: content is a single OBJECT."""
    return FakeBlock(type="web_search_tool_result", content=_SearchError(error_code=error_code))


class _StreamCtx:
    def __init__(self, message: FakeMessage) -> None:
        self._message = message

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> FakeMessage:
        return self._message


class FakeMessages:
    def __init__(self, message: FakeMessage | Exception) -> None:
        self._message = message
        self.calls: list[dict[str, Any]] = []
        self.token_count = 1200

    def stream(self, **kwargs: Any) -> _StreamCtx:
        self.calls.append(kwargs)
        if isinstance(self._message, Exception):
            raise self._message
        return _StreamCtx(self._message)

    def count_tokens(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return type("TokenCount", (), {"input_tokens": self.token_count})()


class FakeAnthropic:
    def __init__(self, message: FakeMessage | Exception) -> None:
        self.messages = FakeMessages(message)


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """No test may touch the real spend ledger in ~/.bie/spend.json."""
    from bie import budget

    monkeypatch.setenv("BIE_LEDGER_PATH", str(tmp_path / "spend.json"))
    monkeypatch.setattr(budget, "daily_spend", budget.DailySpend(path=tmp_path / "spend.json"))
    return budget.daily_spend


@pytest.fixture
def fake_anthropic():
    """Factory: build a fake client whose single call returns `text` (and blocks)."""

    def _make(text: str = "{}", extra_blocks: list[FakeBlock] | None = None, **usage: Any):
        blocks = list(extra_blocks or []) + [FakeBlock(type="text", text=text)]
        return FakeAnthropic(FakeMessage(content=blocks, usage=FakeUsage(**usage)))

    return _make


# --------------------------------------------------------------------------- #
# Sample payloads
# --------------------------------------------------------------------------- #
def text_of(content) -> str:
    """Message content is a list of blocks once attachments are in play."""
    if isinstance(content, str):
        return content
    return "\n".join(b["text"] for b in content if b.get("type") == "text")


@pytest.fixture
def valid_question_set() -> dict:
    topics = [
        "customer",
        "alternative",
        "willingness_to_pay",
        "unfair_advantage",
        "resources",
        "distribution",
        "falsification",
    ]
    return {
        "questions": [
            {"number": i + 1, "text": f"Question about {t}?", "topic": t}
            for i, t in enumerate(topics)
        ],
        "note": None,
    }


@pytest.fixture
def valid_verdict() -> dict:
    return {
        "verdict": "DONT_PROCEED",
        "verdict_condition": None,
        "confidence": "medium",
        "confidence_movers": "Evidence that anyone has paid for this.",
        "works_because": ["Real pain", "Cheap to test", "Founder knows the space"],
        "fails_because": [
            {"rank": 1, "text": "Nobody pays for willpower", "is_guess": False},
            {"rank": 2, "text": "Blockers are free and bundled", "is_guess": False},
            {"rank": 3, "text": "Churn after week two", "is_guess": True},
        ],
        "riskiest_assumption": "That people will pay to be shamed.",
        "validation_plan": {
            "assumption_tested": "Willingness to pay",
            "steps": ["Post in three forums", "Offer pre-orders", "Count buyers"],
            "who_to_talk_to": "People who abandoned a screen-time blocker",
            "pass_threshold": "10 of 50 pre-pay $5",
            "fail_threshold": "Fewer than 3 of 50 pre-pay",
            "duration_days": 10,
            "requires_code": False,
        },
        "research_directions": [
            {
                "question": "What is Opal's retention?",
                "where_to_look": "App Store reviews and Sensor Tower",
                "competitor": "Opal",
                "what_to_check": "Refund complaints",
            }
        ],
        "kill_criteria": ["Fewer than 3 pre-orders in two weeks"],
        "contradictions": [],
        "prior_art": ["Opal", "one sec"],
        "missing_data": ["Retention curves for screen-time apps"],
    }


@pytest.fixture
def tmp_attachments(tmp_path):
    """A small XLSX, PNG, CSV and TXT on disk."""
    from openpyxl import Workbook

    xlsx = tmp_path / "numbers.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "preorders"
    ws.append(["month", "signups", "paid"])
    ws.append(["Jan", 120, 9])
    ws.append(["Feb", 180, 14])
    wb.create_sheet("costs").append(["item", "usd"])
    wb.save(xlsx)

    png = tmp_path / "shot.png"
    png.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
        )
    )

    buf = io.StringIO()
    csv.writer(buf).writerows([["channel", "cac"], ["tiktok", "4.10"]])
    csv_path = tmp_path / "cac.csv"
    csv_path.write_text(buf.getvalue())

    txt = tmp_path / "notes.txt"
    txt.write_text("Interview notes: three of five said they would not pay.")

    return {"xlsx": xlsx, "png": png, "csv": csv_path, "txt": txt}
