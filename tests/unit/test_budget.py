"""T011 — a round that would cost too much never reaches the API."""

from __future__ import annotations

import pytest

from bie.budget import BudgetExceeded, check_round, check_session, project_round_cost
from bie.config import Settings


def test_projection_counts_tokens_output_and_worst_case_searches(fake_anthropic):
    """A research round must be projected as if every allowed search is used."""
    client = fake_anthropic()
    client.messages.token_count = 10_000
    settings = Settings()
    projected = project_round_cost(
        client,
        model="claude-opus-5",
        system="s",
        messages=[],
        settings=settings,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
    )
    # 10k input + 8k output at opus rates, plus 8 searches at $0.01
    assert projected == pytest.approx(10_000 * 5 / 1e6 + 8_000 * 25 / 1e6 + 0.08, rel=1e-6)


def test_projection_without_research_bills_no_searches(fake_anthropic):
    client = fake_anthropic()
    client.messages.token_count = 10_000
    projected = project_round_cost(
        client, model="claude-opus-5", system="s", messages=[], settings=Settings()
    )
    assert projected == pytest.approx(10_000 * 5 / 1e6 + 8_000 * 25 / 1e6, rel=1e-6)


def test_round_under_the_ceiling_passes():
    check_round(0.5, Settings())


def test_round_over_the_ceiling_is_refused():
    with pytest.raises(BudgetExceeded) as exc:
        check_round(2.0, Settings())
    assert "2.0" in str(exc.value) or "2.00" in str(exc.value)
    assert "1.5" in str(exc.value) or "1.50" in str(exc.value)


def test_session_ceiling_counts_what_has_already_been_spent():
    settings = Settings()
    check_session(spent=4.0, projected=0.5, settings=settings)
    with pytest.raises(BudgetExceeded):
        check_session(spent=4.9, projected=0.5, settings=settings)


def test_ceilings_are_configurable(monkeypatch):
    monkeypatch.setenv("BIE_MAX_COST_PER_ROUND_USD", "0.01")
    with pytest.raises(BudgetExceeded):
        check_round(0.02, Settings())


def test_file_blocks_are_stripped_before_counting_and_charged_an_allowance(fake_anthropic):
    """Regression: the counting endpoint 400s on file sources, which broke every
    projection as soon as a founder attached an image or a PDF."""
    from bie.budget import FILE_TOKEN_ALLOWANCE, countable

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "file", "file_id": "file_1"}},
                {"type": "document", "source": {"type": "file", "file_id": "file_2"}},
                {"type": "text", "text": "[IDEA]\nsomething\n[/IDEA]"},
            ],
        },
        {"role": "assistant", "content": "1. Who is the customer?"},
    ]
    cleaned, extra = countable(messages)
    assert extra == 2 * FILE_TOKEN_ALLOWANCE
    assert all(
        b.get("source", {}).get("type") != "file"
        for m in cleaned
        if isinstance(m["content"], list)
        for b in m["content"]
    )
    assert cleaned[1]["content"] == "1. Who is the customer?"

    client = fake_anthropic()
    client.messages.token_count = 1_000
    projected = project_round_cost(
        client, model="claude-opus-5", system="s", messages=messages, settings=Settings()
    )
    sent = client.messages.calls[-1]["messages"]
    assert all(
        b.get("source", {}).get("type") != "file"
        for m in sent
        if isinstance(m["content"], list)
        for b in m["content"]
    )
    assert projected == pytest.approx(
        (1_000 + 2 * FILE_TOKEN_ALLOWANCE) * 5 / 1e6 + 8_000 * 25 / 1e6, rel=1e-6
    )


def test_a_message_that_is_only_files_still_counts_as_something(fake_anthropic):
    from bie.budget import countable

    cleaned, _ = countable(
        [{"role": "user", "content": [{"type": "image", "source": {"type": "file", "file_id": "f"}}]}]
    )
    assert cleaned[0]["content"] == [{"type": "text", "text": "(attachment)"}]
