"""T027 — POST /api/questions."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from bie.api import create_app

IDEA = "A subscription app that shames you with your own voice when you doomscroll past a limit."


def client_for(fake) -> TestClient:
    return TestClient(create_app(client_factory=lambda: fake), raise_server_exceptions=False)


def test_happy_path(fake_anthropic, valid_question_set):
    fake = fake_anthropic(json.dumps(valid_question_set))
    response = client_for(fake).post("/api/questions", json={"idea": IDEA})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "questions"
    assert len(body["questions"]["questions"]) == 7
    assert body["usage"]["model"] == "claude-opus-5"
    assert body["cost_usd"] > 0


def test_short_idea_is_refused_before_any_call(fake_anthropic, valid_question_set):
    fake = fake_anthropic(json.dumps(valid_question_set))
    response = client_for(fake).post("/api/questions", json={"idea": "an app"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idea_too_short"
    assert fake.messages.calls == []


def test_budget_refusal_is_402(fake_anthropic, valid_question_set, monkeypatch):
    monkeypatch.setenv("BIE_MAX_COST_PER_ROUND_USD", "0.0001")
    fake = fake_anthropic(json.dumps(valid_question_set))
    response = client_for(fake).post("/api/questions", json={"idea": IDEA})
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert response.json()["error"]["retryable"] is False


def test_invalid_model_output_is_500_and_shows_nothing(fake_anthropic):
    fake = fake_anthropic("not json")
    response = client_for(fake).post("/api/questions", json={"idea": IDEA})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "invalid_model_output"
    assert body["error"]["retryable"] is True
    assert "questions" not in body


def test_upstream_failure_is_502():
    import anthropic

    from tests.conftest import FakeAnthropic

    fake = FakeAnthropic(anthropic.APITimeoutError.__new__(anthropic.APITimeoutError))
    fake.messages.token_count = 100
    response = client_for(fake).post("/api/questions", json={"idea": IDEA})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_timeout"


@pytest.mark.parametrize("payload", [{}, {"idea": None}])
def test_malformed_requests_are_rejected(fake_anthropic, valid_question_set, payload):
    fake = fake_anthropic(json.dumps(valid_question_set))
    assert client_for(fake).post("/api/questions", json=payload).status_code == 422
