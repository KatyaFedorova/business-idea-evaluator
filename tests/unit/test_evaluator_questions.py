"""T025 — round one asks, and only asks."""

from __future__ import annotations

import json

import pytest

from bie.config import Settings
from bie.errors import IdeaTooShort, InvalidModelOutput
from bie.evaluator import ask_questions
from bie.schemas import Attachment
from tests.conftest import text_of

IDEA = "A subscription app that shames you with your own voice when you doomscroll."


def test_returns_a_question_round(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    round_ = ask_questions(IDEA, client=client, settings=Settings())
    assert round_.kind == "questions"
    assert round_.index == 0
    assert round_.questions is not None
    assert round_.report is None
    assert round_.cost_usd > 0
    assert round_.submission[0].text == IDEA


def test_short_idea_never_reaches_the_model(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    with pytest.raises(IdeaTooShort):
        ask_questions("an app", client=client, settings=Settings())
    assert client.messages.calls == []


def test_the_idea_is_sent_as_data_not_instructions(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    ask_questions(IDEA, client=client, settings=Settings())
    call = client.messages.calls[-1]
    content = text_of(call["messages"][0]["content"])
    assert "[IDEA]" in content and "[/IDEA]" in content
    assert IDEA in content
    assert "STEP 1" in "".join(block["text"] for block in call["system"])


def test_question_rounds_do_not_research(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    ask_questions(IDEA, client=client, settings=Settings())
    assert not client.messages.calls[-1].get("tools")


def test_a_leaked_verdict_is_an_error_not_a_round(fake_anthropic, valid_question_set):
    valid_question_set["questions"][0]["text"] = "VERDICT: DON'T PROCEED. Who is the customer?"
    client = fake_anthropic(json.dumps(valid_question_set))
    with pytest.raises(InvalidModelOutput):
        ask_questions(IDEA, client=client, settings=Settings())


def test_attachment_text_travels_with_the_idea(fake_anthropic, valid_question_set):
    client = fake_anthropic(json.dumps(valid_question_set))
    attachment = Attachment(
        id="a1", filename="numbers.xlsx", kind="sheet", size_bytes=99, text="month\tsignups"
    )
    ask_questions(IDEA, attachments=[attachment], client=client, settings=Settings())
    content = text_of(client.messages.calls[-1]["messages"][0]["content"])
    assert "[ATTACHMENT numbers.xlsx]" in content
