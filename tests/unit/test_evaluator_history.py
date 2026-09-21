"""T045 — every later round carries everything said so far."""

from __future__ import annotations

import json

from bie.config import Settings
from bie.evaluator import evaluate
from bie.schemas import FounderMessage, QuestionSet, Round
from tests.conftest import text_of

IDEA = "A subscription app that shames you with your own voice when you doomscroll daily."
REVISED = "A one-off $29 app that shames you with your own voice when you doomscroll daily."


def _history(valid_question_set) -> list[Round]:
    return [
        Round(
            index=0,
            kind="questions",
            submission=[FounderMessage(text=IDEA)],
            questions=QuestionSet.model_validate(valid_question_set),
        ),
        Round(
            index=1,
            kind="reask",
            submission=[FounderMessage(text="everyone in an office")],
            questions=QuestionSet.model_validate({**valid_question_set, "note": "too vague"}),
        ),
    ]


def _call(client, idea=IDEA, answers=None, **kw):
    return evaluate(
        idea,
        rounds=_history(kw.pop("question_set")),
        answers=answers or [FounderMessage(text="People who abandoned three blockers.")],
        client=client,
        settings=Settings(),
        **kw,
    )


def test_every_earlier_turn_is_replayed(fake_anthropic, valid_question_set, valid_verdict):
    client = fake_anthropic(
        json.dumps({"decision": "verdict", "reask": None, "report": valid_verdict})
    )
    _call(client, question_set=valid_question_set)
    messages = client.messages.calls[-1]["messages"]
    roles = [m["role"] for m in messages]
    assert roles[0] == "user"
    assert roles.count("assistant") == 2  # the questions and the re-ask
    blob = json.dumps(messages)
    assert "everyone in an office" in blob
    assert "too vague" in blob
    assert "People who abandoned three blockers." in blob


def test_several_messages_in_one_answer_all_travel(
    fake_anthropic, valid_question_set, valid_verdict
):
    client = fake_anthropic(
        json.dumps({"decision": "verdict", "reask": None, "report": valid_verdict})
    )
    _call(
        client,
        question_set=valid_question_set,
        answers=[
            FounderMessage(text="First: people who abandoned three blockers."),
            FounderMessage(text="Second: I forgot to say pricing is $4.99."),
        ],
    )
    blob = json.dumps(client.messages.calls[-1]["messages"])
    assert "First: people who abandoned" in blob
    assert "Second: I forgot to say pricing" in blob


def test_a_revised_idea_is_what_gets_evaluated(fake_anthropic, valid_question_set, valid_verdict):
    client = fake_anthropic(
        json.dumps({"decision": "verdict", "reask": None, "report": valid_verdict})
    )
    _call(client, idea=REVISED, question_set=valid_question_set)
    opening = text_of(client.messages.calls[-1]["messages"][0]["content"])
    assert REVISED in opening
    assert "subscription" not in opening.split("[/IDEA]")[0]
