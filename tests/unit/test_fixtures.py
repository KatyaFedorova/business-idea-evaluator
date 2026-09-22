"""Recording a reply once, and replaying it for free."""

from __future__ import annotations

import json

from bie import fixtures
from tests.conftest import FakeMessage, FakeUsage, search_result_block


def test_a_reply_round_trips_through_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(fixtures, "FIXTURE_DIR", tmp_path)
    message = FakeMessage(
        content=[search_result_block(("https://example.com", "A"))],
        usage=FakeUsage(input_tokens=11, output_tokens=22),
        model="claude-sonnet-5",
    )

    path = fixtures.record(message, label="verdict")
    assert path.parent == tmp_path
    assert path.name.startswith("verdict-")

    saved = json.loads(path.read_text())
    assert saved["model"] == "claude-sonnet-5"
    assert saved["usage"]["input_tokens"] == 11

    replayed = fixtures.load(path)
    assert replayed.model == "claude-sonnet-5"
    assert replayed.usage.output_tokens == 22
    assert replayed.content[0].type == "web_search_tool_result"
    assert replayed.content[0].content[0].url == "https://example.com"


def test_recording_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("BIE_RECORD", raising=False)
    assert fixtures.recording_enabled() is False
    monkeypatch.setenv("BIE_RECORD", "0")
    assert fixtures.recording_enabled() is False
    monkeypatch.setenv("BIE_RECORD", "1")
    assert fixtures.recording_enabled() is True


def test_replay_path_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("BIE_REPLAY", raising=False)
    assert fixtures.replay_path() is None
    monkeypatch.setenv("BIE_REPLAY", str(tmp_path / "r.json"))
    assert fixtures.replay_path() == tmp_path / "r.json"
