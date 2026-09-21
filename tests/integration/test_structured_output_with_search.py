"""T019 — settles research.md §3: can one call combine structured output with web search?

Marked `live`: it calls the real API and costs money. Run with `pytest -m live`.
"""

from __future__ import annotations

import os

import pytest

from bie.claude import build_client, complete
from bie.config import Settings
from bie.schemas import QuestionSet

pytestmark = pytest.mark.live


@pytest.mark.skipif(not Settings().has_api_key, reason="no ANTHROPIC_API_KEY in the environment")
def test_structured_output_and_web_search_in_one_call():
    settings = Settings()
    reply = complete(
        build_client(),
        system=(
            "You are interviewing a founder. Ask 3 to 10 numbered questions and return them "
            "in the given schema. Do not evaluate the idea."
        ),
        messages=[
            {
                "role": "user",
                "content": "IDEA: A subscription app that shames you when you doomscroll.",
            }
        ],
        schema=QuestionSet,
        effort=settings.question_effort,
        settings=settings,
        research=True,
    )
    assert isinstance(reply.parsed, QuestionSet)
    assert reply.usage.cost_usd > 0
    assert os.environ.get("ANTHROPIC_API_KEY") not in repr(reply)
