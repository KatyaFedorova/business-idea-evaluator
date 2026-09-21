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
