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


# --- the daily ceiling ----------------------------------------------------- #
def test_the_daily_ledger_accumulates_and_refuses(tmp_path):
    """A per-session cap does nothing about a hundred sessions."""
    from bie.budget import DailySpend, check_daily, record_spend

    ledger = DailySpend(path=tmp_path / "acc.json")
    settings = Settings()
    check_daily(1.0, settings, ledger)  # nothing spent yet

    for _ in range(4):
        record_spend(0.45, ledger)
    assert ledger.spent == pytest.approx(1.8)

    check_daily(0.15, settings, ledger)  # 1.95 total, still under the $2 day cap
    with pytest.raises(BudgetExceeded) as exc:
        check_daily(0.30, settings, ledger)
    assert "2.00" in str(exc.value)
    assert "tomorrow" in str(exc.value)


def test_the_daily_ledger_rolls_over_at_midnight_utc(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta

    from bie import budget

    ledger = budget.DailySpend(path=tmp_path / "rollover.json")
    ledger.add(1.99)
    assert ledger.spent == pytest.approx(1.99)

    tomorrow = datetime.now(UTC) + timedelta(days=1)

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return tomorrow

    monkeypatch.setattr(budget, "datetime", FakeDatetime)
    assert ledger.spent == 0.0


def test_the_daily_ceiling_is_configurable(monkeypatch):
    from bie.budget import DailySpend, check_daily

    monkeypatch.setenv("BIE_MAX_COST_PER_DAY_USD", "0.50")
    ledger = DailySpend(path=None)
    ledger.add(0.45)
    with pytest.raises(BudgetExceeded):
        check_daily(0.10, Settings(), ledger)


def test_the_ledger_outlives_the_process(tmp_path):
    """Without this, every local script started at $0 and the cap never bit."""
    from bie.budget import DailySpend

    path = tmp_path / "spend.json"
    first = DailySpend(path=path)
    first.add(0.35)
    first.add(0.15)
    assert first.spent == pytest.approx(0.50)

    second = DailySpend(path=path)  # a fresh process reading the same file
    assert second.spent == pytest.approx(0.50)

    second.add(0.25)
    assert DailySpend(path=path).spent == pytest.approx(0.75)

    second.reset()
    assert DailySpend(path=path).spent == 0.0


def test_a_ledger_from_yesterday_is_ignored(tmp_path):
    import json
    from datetime import UTC, datetime, timedelta

    from bie.budget import DailySpend

    path = tmp_path / "spend.json"
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    path.write_text(json.dumps({"day": yesterday, "spent_usd": 1.99}))
    assert DailySpend(path=path).spent == 0.0


def test_a_corrupt_ledger_does_not_stop_the_app(tmp_path):
    from bie.budget import DailySpend

    path = tmp_path / "spend.json"
    path.write_text("{not json at all")
    assert DailySpend(path=path).spent == 0.0


def test_a_read_only_location_keeps_the_in_memory_brake(tmp_path):
    from bie.budget import DailySpend

    ledger = DailySpend(path=tmp_path / "nope" / "deep" / "spend.json")
    (tmp_path / "nope").mkdir()
    (tmp_path / "nope").chmod(0o500)
    try:
        ledger.add(0.40)
        assert ledger.spent == pytest.approx(0.40)
    finally:
        (tmp_path / "nope").chmod(0o700)


def test_a_failed_round_is_still_charged(fake_anthropic):
    """The call was billed; costing it only on success hid the expensive failures."""
    from bie import budget
    from bie.claude import complete
    from bie.errors import InvalidModelOutput
    from bie.schemas import QuestionSet

    budget.daily_spend.reset()
    before = budget.daily_spend.spent
    client = fake_anthropic("not valid json")
    with pytest.raises(InvalidModelOutput) as exc:
        complete(
            client,
            system="s",
            messages=[{"role": "user", "content": "i"}],
            schema=QuestionSet,
            effort="medium",
            settings=Settings(),
        )
    assert exc.value.usage is not None
    assert exc.value.usage.cost_usd > 0
    assert budget.daily_spend.spent > before
