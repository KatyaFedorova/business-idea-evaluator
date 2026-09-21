"""T028 — POST /api/verdict."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from bie.api import create_app
from tests.conftest import search_error_block, search_result_block

IDEA = "A subscription app that shames you with your own voice when you doomscroll past a limit."


def decision(report: dict) -> str:
    return json.dumps({"decision": "verdict", "reask": None, "report": report})


def client_for(fake) -> TestClient:
    return TestClient(create_app(client_factory=lambda: fake), raise_server_exceptions=False)


def body(valid_question_set) -> dict:
    return {
        "idea": IDEA,
        "rounds": [
            {
                "index": 0,
                "kind": "questions",
                "submission": [{"text": IDEA, "attachment_ids": []}],
                "questions": valid_question_set,
            }
        ],
        "answers": [{"text": "1. People who quit three blockers. 2. They uninstall them."}],
        "spent": 0.0,
    }


def test_happy_path(fake_anthropic, valid_question_set, valid_verdict):
    fake = fake_anthropic(
        decision(valid_verdict),
        extra_blocks=[search_result_block(("https://example.com/opal", "Opal"))],
    )
    response = client_for(fake).post("/api/verdict", json=body(valid_question_set))
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "verdict"
    assert payload["report"]["verdict"] == "DONT_PROCEED"
    assert payload["sources"][0]["url"] == "https://example.com/opal"
    assert payload["research_status"] == "ok"
    assert payload["cost_usd"] > 0


def test_degraded_research_is_still_a_200_verdict(
    fake_anthropic, valid_question_set, valid_verdict
):
    fake = fake_anthropic(
        decision(valid_verdict), extra_blocks=[search_error_block("unavailable")]
    )
    response = client_for(fake).post("/api/verdict", json=body(valid_question_set))
    assert response.status_code == 200
    assert response.json()["research_status"] == "degraded"
    assert response.json()["report"] is not None


def test_session_ceiling_is_402(fake_anthropic, valid_question_set, valid_verdict):
    fake = fake_anthropic(decision(valid_verdict))
    payload = body(valid_question_set) | {"spent": 4.99}
    response = client_for(fake).post("/api/verdict", json=payload)
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "budget_exceeded"


def test_invalid_output_is_500(fake_anthropic, valid_question_set):
    fake = fake_anthropic("{}")
    response = client_for(fake).post("/api/verdict", json=body(valid_question_set))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "invalid_model_output"


def test_a_vague_answer_comes_back_as_a_reask(fake_anthropic, valid_question_set):
    """T044 — the client branches on `kind` alone, never on the payload's shape."""
    noted = {**valid_question_set, "note": "'Everyone in an office' is not a customer."}
    fake = fake_anthropic(
        json.dumps({"decision": "reask", "reask": noted, "report": None})
    )
    response = client_for(fake).post("/api/verdict", json=body(valid_question_set))
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "reask"
    assert payload["report"] is None
    assert payload["questions"]["note"].startswith("'Everyone in an office'")
