"""T061 — a real round with a spreadsheet and an image. Marked `live`: costs money."""

from __future__ import annotations

import pytest

from bie.attachments import prepare_files
from bie.claude import build_client
from bie.config import Settings
from bie.evaluator import ask_questions, evaluate
from bie.schemas import FounderMessage

pytestmark = pytest.mark.live

IDEA = (
    "A subscription app that shames you with your own voice when you doomscroll. $4.99 a "
    "month. I ran a small pre-order test and the numbers are in the attached spreadsheet."
)


@pytest.mark.skipif(not Settings().has_api_key, reason="no ANTHROPIC_API_KEY in the environment")
def test_the_verdict_uses_the_attached_evidence(tmp_attachments):
    settings = Settings()
    client = build_client()
    attachments = prepare_files(
        [tmp_attachments["xlsx"], tmp_attachments["png"]], client=client, settings=settings
    )
    assert [a.readable for a in attachments] == [True, True]
    assert attachments[0].text and "preorders" in attachments[0].text
    assert attachments[1].file_id

    first = ask_questions(IDEA, attachments=attachments, settings=settings, client=client)
    second = evaluate(
        IDEA,
        rounds=[first],
        answers=[
            FounderMessage(
                text=(
                    "1. People who abandoned three blockers. 2. They uninstall and reinstall. "
                    "3. The attached sheet is the pre-order test: 180 February signups, 14 paid. "
                    "4. I built the Screen Time integration. 5. Ten hours a week. 6. TikTok. "
                    "7. If the paid rate stays under 10 percent I am wrong."
                ),
                attachment_ids=[a.id for a in attachments],
            )
        ],
        attachments=attachments,
        settings=settings,
        client=client,
        spent=first.cost_usd,
    )
    if second.kind == "verdict":
        blob = second.model_dump_json()
        assert "14" in blob or "180" in blob
