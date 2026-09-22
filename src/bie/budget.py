"""Cost control. A round that would cost too much never reaches the API.

The constitution requires the ceiling to be enforced in code, before the spend,
not reconciled after it.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime
from typing import Any

from bie.config import Settings
from bie.errors import BudgetExceeded
from bie.pricing import WEB_SEARCH_COST_PER_SEARCH_USD, cost_usd

__all__ = [
    "BudgetExceeded",
    "DailySpend",
    "check_daily",
    "check_round",
    "check_session",
    "countable",
    "daily_spend",
    "project_round_cost",
    "record_spend",
]

# The token-counting endpoint refuses file sources ("File sources are not supported in
# the token counting endpoint"), so an attached image or PDF is replaced by a placeholder
# and charged this allowance instead. Deliberately generous: a projection that guesses low
# would let a round through that the ceiling exists to stop.
FILE_TOKEN_ALLOWANCE = 3000


def countable(messages: list[dict]) -> tuple[list[dict], int]:
    """Messages the counting endpoint accepts, plus tokens to add for what was removed."""
    cleaned: list[dict] = []
    removed = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            cleaned.append(message)
            continue
        blocks = []
        for block in content:
            source = block.get("source") if isinstance(block, dict) else None
            if isinstance(source, dict) and source.get("type") == "file":
                removed += 1
                continue
            blocks.append(block)
        if not blocks:
            blocks = [{"type": "text", "text": "(attachment)"}]
        cleaned.append({**message, "content": blocks})
    return cleaned, removed * FILE_TOKEN_ALLOWANCE


def project_round_cost(
    client: Any,
    *,
    model: str,
    system: Any,
    messages: list[dict],
    settings: Settings,
    tools: list[dict] | None = None,
) -> float:
    """Worst case for one round: counted input, full output budget, every search used."""
    safe_messages, file_tokens = countable(messages)
    counted = client.messages.count_tokens(model=model, system=system, messages=safe_messages)
    input_tokens = getattr(counted, "input_tokens", 0) + file_tokens
    searches = settings.max_searches if tools else 0
    return cost_usd(
        model,
        input_tokens=input_tokens,
        output_tokens=settings.max_tokens,
        web_searches=searches,
    )


def check_round(projected_usd: float, settings: Settings) -> None:
    if projected_usd > settings.max_cost_per_round_usd:
        raise BudgetExceeded(
            f"This round would cost about ${projected_usd:.2f}, over the "
            f"${settings.max_cost_per_round_usd:.2f} limit for a single round. "
            "Shorten the idea or remove an attachment.",
            detail=f"projected={projected_usd} ceiling={settings.max_cost_per_round_usd}",
        )


def check_session(*, spent: float, projected: float, settings: Settings) -> None:
    if spent + projected > settings.max_cost_per_session_usd:
        raise BudgetExceeded(
            f"This session has spent ${spent:.2f} and this round would add about "
            f"${projected:.2f}, over the ${settings.max_cost_per_session_usd:.2f} session "
            "limit. Start a new session to continue.",
            detail=f"spent={spent} projected={projected}",
        )


def search_cost(searches: int) -> float:
    return searches * WEB_SEARCH_COST_PER_SEARCH_USD


class DailySpend:
    """Today's spend, shared by every request this process serves.

    A per-session ceiling stops one founder running away with your money. It does
    nothing about a hundred founders, which is the shape of the risk the moment the
    URL is public. This is the day-level stop.

    Deliberately in-process: the constitution fixes a stack with no database, and a
    counter in memory is honest about what it is. It resets when the process restarts
    and it is per instance, so it is a brake, not a guarantee. The guarantee belongs
    in the Anthropic Console as a monthly budget on the key.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: date = datetime.now(UTC).date()
        self._spent: float = 0.0

    def _roll(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day = today
            self._spent = 0.0

    @property
    def spent(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    def add(self, amount: float) -> float:
        with self._lock:
            self._roll()
            self._spent += max(0.0, amount)
            return self._spent

    def reset(self) -> None:
        with self._lock:
            self._day = datetime.now(UTC).date()
            self._spent = 0.0


daily_spend = DailySpend()


def check_daily(projected: float, settings: Settings, ledger: DailySpend | None = None) -> None:
    """Refuse a round that would take today's total past the daily ceiling."""
    ledger = ledger or daily_spend
    spent = ledger.spent
    if spent + projected > settings.max_cost_per_day_usd:
        raise BudgetExceeded(
            f"This site has spent its daily budget of "
            f"${settings.max_cost_per_day_usd:.2f} on evaluations. Come back tomorrow.",
            detail=f"spent_today={spent} projected={projected}",
        )


def record_spend(amount: float, ledger: DailySpend | None = None) -> float:
    """Called after a round returns, with what it actually cost."""
    return (ledger or daily_spend).add(amount)
