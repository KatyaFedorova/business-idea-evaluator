"""The Groq adapter answers the Anthropic-shaped calls the app makes. No network."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from bie import groq
from bie.attachments import prepare_uploads
from bie.claude import build_client, complete
from bie.config import Settings
from bie.errors import InvalidModelOutput, RateLimited
from bie.schemas import QuestionSet


@pytest.fixture(autouse=True)
def groq_provider(monkeypatch):
    monkeypatch.setenv("BIE_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")


def chat_reply(text: str, prompt_tokens: int = 100, completion_tokens: int = 50) -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


@pytest.fixture
def posted(monkeypatch):
    """Queue replies for the adapter; record every body it sends."""
    bodies: list[dict] = []
    queue: list[dict] = []

    def fake_post(self, body):
        bodies.append(json.loads(json.dumps(body)))
        return queue.pop(0)

    monkeypatch.setattr(groq._Messages, "_post", fake_post)
    return bodies, queue


def test_groq_settings_use_the_open_model_everywhere_with_research_off():
    settings = Settings()
    assert settings.model == settings.judge_model == settings.eval_model == settings.groq_model
    assert settings.max_searches == 0
    assert not settings.research_enabled
    assert settings.has_api_key


def test_build_client_picks_groq():
    assert isinstance(build_client(), groq.GroqClient)


def test_messages_are_flattened_and_the_schema_is_spelled_out():
    chat = groq.to_chat_messages(
        [{"type": "text", "text": "PROMPT"}, {"type": "text", "text": "STEP 1"}],
        [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "file", "file_id": "f"}},
                    {"type": "text", "text": "[IDEA]\nan idea\n[/IDEA]"},
                ],
            }
        ],
        QuestionSet,
    )
    assert chat[0]["role"] == "system"
    assert "PROMPT" in chat[0]["content"] and "STEP 1" in chat[0]["content"]
    assert '"questions"' in chat[0]["content"]  # the JSON schema
    assert chat[1] == {"role": "user", "content": "[IDEA]\nan idea\n[/IDEA]"}


def test_complete_returns_a_validated_model_at_zero_cost(posted, valid_question_set):
    bodies, queue = posted
    queue.append(chat_reply(json.dumps(valid_question_set)))
    settings = Settings()

    reply = complete(
        build_client(),
        system="PROMPT",
        messages=[{"role": "user", "content": "idea"}],
        schema=QuestionSet,
        effort="medium",
        settings=settings,
    )

    assert isinstance(reply.parsed, QuestionSet)
    assert bodies[0]["model"] == settings.groq_model
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert reply.usage.input_tokens == 100
    assert reply.usage.cost_usd == 0.0


def test_a_bad_reply_gets_one_retry_told_what_failed(posted, valid_question_set):
    bodies, queue = posted
    queue += [chat_reply('{"questions": []}'), chat_reply(json.dumps(valid_question_set))]

    reply = complete(
        build_client(),
        system="PROMPT",
        messages=[{"role": "user", "content": "idea"}],
        schema=QuestionSet,
        effort="medium",
        settings=Settings(),
    )

    assert len(bodies) == 2
    assert "failed validation" in bodies[1]["messages"][-1]["content"]
    assert reply.usage.input_tokens == 200  # both calls counted


def test_two_bad_replies_are_an_error_not_a_patch(posted):
    _, queue = posted
    queue += [chat_reply("not json"), chat_reply("still not json")]
    with pytest.raises(InvalidModelOutput):
        complete(
            build_client(),
            system="PROMPT",
            messages=[{"role": "user", "content": "idea"}],
            schema=QuestionSet,
            effort="medium",
            settings=Settings(),
        )


def test_rate_limit_waits_then_says_so(monkeypatch):
    calls = []

    def limited(*a, **kw):
        calls.append(1)
        raise urllib.error.HTTPError(
            groq.GROQ_URL, 429, "Too Many Requests", {"retry-after": "1"}, io.BytesIO(b"slow")
        )

    monkeypatch.setattr(groq.urllib.request, "urlopen", limited)
    monkeypatch.setattr(groq.time, "sleep", lambda s: None)
    with pytest.raises(RateLimited):
        groq._Messages("k")._post({})
    assert len(calls) == groq.RATE_LIMIT_ATTEMPTS


def test_images_are_marked_unreadable_but_text_still_works():
    attachments = prepare_uploads(
        [("shot.png", "image/png", b"\x89PNG"), ("notes.txt", "text/plain", b"three said no")],
        client=build_client(),
    )
    image, text = attachments
    assert not image.readable and image.error == "NotSupportedOnGroq"
    assert text.readable and text.text == "three said no"


def test_token_projection_needs_no_endpoint():
    counted = build_client().messages.count_tokens(
        model="m", system="x" * 400, messages=[{"role": "user", "content": "y" * 400}]
    )
    assert counted.input_tokens == 200
