"""T029 — the CLI runs the same rounds as the API, with distinct exit codes."""

from __future__ import annotations

import json

import anthropic
import pytest
from typer.testing import CliRunner

from bie import cli
from tests.conftest import FakeAnthropic

runner = CliRunner()
IDEA = "A subscription app that shames you with your own voice when you doomscroll past a limit."


@pytest.fixture
def patched(monkeypatch, fake_anthropic):
    def _patch(fake):
        monkeypatch.setattr(cli, "build_client", lambda: fake)
        return fake

    return _patch


def test_ask_prints_the_questions(patched, fake_anthropic, valid_question_set):
    patched(fake_anthropic(json.dumps(valid_question_set)))
    result = runner.invoke(cli.app, ["ask", IDEA])
    assert result.exit_code == 0
    assert "1." in result.stdout
    assert "$" in result.stdout  # the round's cost is always shown


def test_ask_json_prints_the_validated_round(patched, fake_anthropic, valid_question_set):
    patched(fake_anthropic(json.dumps(valid_question_set)))
    result = runner.invoke(cli.app, ["ask", IDEA, "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["kind"] == "questions"
    assert len(payload["questions"]["questions"]) == 7


def test_short_idea_exits_two(patched, fake_anthropic, valid_question_set):
    patched(fake_anthropic(json.dumps(valid_question_set)))
    result = runner.invoke(cli.app, ["ask", "an app"])
    assert result.exit_code == 2


def test_budget_refusal_exits_three(patched, fake_anthropic, valid_question_set, monkeypatch):
    monkeypatch.setenv("BIE_MAX_COST_PER_ROUND_USD", "0.0001")
    patched(fake_anthropic(json.dumps(valid_question_set)))
    assert runner.invoke(cli.app, ["ask", IDEA]).exit_code == 3


def test_invalid_output_exits_four(patched, fake_anthropic):
    patched(fake_anthropic("nonsense"))
    assert runner.invoke(cli.app, ["ask", IDEA]).exit_code == 4


def test_upstream_failure_exits_five(patched):
    fake = FakeAnthropic(anthropic.RateLimitError.__new__(anthropic.RateLimitError))
    fake.messages.token_count = 100
    patched(fake)
    assert runner.invoke(cli.app, ["ask", IDEA]).exit_code == 5


def test_ask_writes_a_session_that_verdict_continues(
    patched, fake_anthropic, valid_question_set, valid_verdict, tmp_path
):
    session = tmp_path / "session.json"
    patched(fake_anthropic(json.dumps(valid_question_set)))
    assert runner.invoke(cli.app, ["ask", IDEA, "--session", str(session)]).exit_code == 0
    saved = json.loads(session.read_text())
    assert saved["idea"] == IDEA
    assert len(saved["rounds"]) == 1

    patched(
        fake_anthropic(json.dumps({"decision": "verdict", "reask": None, "report": valid_verdict}))
    )
    result = runner.invoke(
        cli.app, ["verdict", "--session", str(session), "--answers", "They uninstall blockers."]
    )
    assert result.exit_code == 0
    assert "DON'T PROCEED" in result.stdout or "DONT_PROCEED" in result.stdout
    saved = json.loads(session.read_text())
    assert len(saved["rounds"]) == 2
    assert saved["total_cost_usd"] > 0


def test_model_override_reaches_the_call(patched, fake_anthropic, valid_question_set):
    fake = patched(fake_anthropic(json.dumps(valid_question_set)))
    runner.invoke(cli.app, ["ask", IDEA, "--model", "claude-sonnet-5"])
    assert fake.messages.calls[-1]["model"] == "claude-sonnet-5"
