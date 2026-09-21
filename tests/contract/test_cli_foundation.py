"""T023 — the CLI exists, lists its commands, and takes per-run overrides."""

from __future__ import annotations

from typer.testing import CliRunner

from bie.cli import app

runner = CliRunner()


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["ask", "verdict", "evaluate", "serve", "eval"]:
        assert command in result.stdout


def test_overrides_are_documented():
    result = runner.invoke(app, ["ask", "--help"])
    assert result.exit_code == 0
    for option in ["--model", "--effort", "--prompt-version", "--json"]:
        assert option in result.stdout
