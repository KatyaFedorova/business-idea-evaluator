"""T032 — the whole loop against the real API. Marked `live`: it costs money."""

from __future__ import annotations

import pytest

from bie.claude import build_client
from bie.config import Settings
from bie.evaluator import ask_questions, evaluate
from bie.schemas import FounderMessage

pytestmark = pytest.mark.live

IDEA = (
    "A subscription iOS app that plays a recording of your own voice shaming you when you "
    "doomscroll past your daily limit. $4.99 a month, aimed at people who have already "
    "abandoned three screen-time blockers."
)
ANSWERS = (
    "1. People aged 20-35 who already paid for and abandoned Opal. 2. They delete the app and "
    "reinstall a week later. 3. Nobody has paid me yet. 4. I already built the Screen Time "
    "integration and have 4,000 followers who complain about this. 5. Ten hours a week and "
    "$3,000. 6. TikTok. 7. If fewer than 10 of 50 people pre-pay $5 in two weeks, I am wrong."
)


@pytest.mark.skipif(not Settings().has_api_key, reason="no ANTHROPIC_API_KEY in the environment")
def test_idea_to_questions_to_verdict():
    settings = Settings()
    client = build_client()

    first = ask_questions(IDEA, settings=settings, client=client)
    assert first.kind == "questions"
    assert 3 <= len(first.questions.questions) <= 10
    assert first.report is None
    assert first.cost_usd > 0

    second = evaluate(
        IDEA,
        rounds=[first],
        answers=[FounderMessage(text=ANSWERS)],
        settings=settings,
        client=client,
        spent=first.cost_usd,
    )
    assert second.kind in ("verdict", "reask")
    if second.kind == "verdict":
        assert second.report.verdict in (
            "PROCEED",
            "PROCEED_ONLY_AFTER_TESTING",
            "DONT_PROCEED",
        )
        assert second.report.word_count <= 400
        assert second.report.validation_plan.requires_code is False
    assert second.cost_usd > 0
