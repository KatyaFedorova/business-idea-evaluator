"""T021 — health, limits, and the error envelope."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bie.api import create_app
from bie.config import Settings
from bie.errors import BudgetExceeded, InvalidModelOutput, UpstreamError


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_app_is_a_fastapi_app():
    assert isinstance(create_app(), FastAPI)


def test_health_reports_config_without_raising(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["model"] == Settings().model
    assert body["prompt_version"] == Settings().prompt_version
    assert body["has_api_key"] is False


def test_limits_match_settings(client):
    settings = Settings()
    body = client.get("/api/limits").json()
    assert body["min_idea_chars"] == settings.min_idea_chars
    assert body["max_attachments"] == settings.max_attachments
    assert body["max_attachment_bytes"] == settings.max_attachment_bytes
    assert body["max_cost_per_round_usd"] == settings.max_cost_per_round_usd
    assert body["max_cost_per_session_usd"] == settings.max_cost_per_session_usd
    assert "image/png" in body["allowed_media_types"]
    assert "application/pdf" in body["allowed_media_types"]


@pytest.mark.parametrize(
    ("error", "status", "code", "retryable"),
    [
        (BudgetExceeded("too dear"), 402, "budget_exceeded", False),
        (InvalidModelOutput("bad reply"), 500, "invalid_model_output", True),
        (UpstreamError("no reach", detail="api_key=sk-ant-secret"), 502, "upstream_error", True),
    ],
)
def test_errors_render_as_the_envelope(error, status, code, retryable):
    app = create_app(mount_static=False)

    @app.get("/boom")
    def boom():
        raise error

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == status
    assert response.json() == {
        "error": {"code": code, "message": error.message, "retryable": retryable}
    }
    assert "sk-ant-secret" not in response.text


def test_the_page_is_served_at_the_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Business Idea Evaluator" in response.text


def test_limits_reports_the_daily_budget_and_what_is_left(client):
    from bie.budget import daily_spend

    daily_spend.reset()
    body = client.get("/api/limits").json()
    assert body["max_cost_per_day_usd"] == Settings().max_cost_per_day_usd
    assert body["spent_today_usd"] == 0.0

    daily_spend.add(0.25)
    assert client.get("/api/limits").json()["spent_today_usd"] == 0.25
    daily_spend.reset()


def test_a_round_is_refused_once_the_day_is_spent(fake_anthropic, valid_question_set):
    """Regression guard for a public URL: the session cap does not bound the day."""
    import json

    from bie.budget import daily_spend

    daily_spend.reset()
    daily_spend.add(4.99)
    fake = fake_anthropic(json.dumps(valid_question_set))
    response = TestClient(
        create_app(client_factory=lambda: fake), raise_server_exceptions=False
    ).post("/api/questions", json={"idea": "A" * 60})
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert "tomorrow" in response.json()["error"]["message"]
    assert fake.messages.calls[-1].get("messages") is None or "output_format" not in fake.messages.calls[-1]
    daily_spend.reset()


def test_error_detail_is_logged_even_though_it_is_not_returned(caplog):
    """The envelope hides internal detail from the founder; it must still reach the log,
    or a production failure leaves nothing to diagnose."""
    import logging

    app = create_app(mount_static=False)

    @app.get("/boom")
    def boom():
        raise UpstreamError("We could not reach the evaluator.", detail="why it really broke")

    with caplog.at_level(logging.WARNING, logger="bie"):
        response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 502
    assert "why it really broke" not in response.text
    assert "why it really broke" in caplog.text
    assert "upstream_error" in caplog.text
