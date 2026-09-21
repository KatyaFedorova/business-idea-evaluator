"""Cost control. A round that would cost too much never reaches the API.

The constitution requires the ceiling to be enforced in code, before the spend,
not reconciled after it.
"""

from __future__ import annotations

from typing import Any

from bie.config import Settings
from bie.errors import BudgetExceeded
from bie.pricing import WEB_SEARCH_COST_PER_SEARCH_USD, cost_usd

__all__ = [
    "BudgetExceeded",
    "check_round",
    "check_session",
    "countable",
    "project_round_cost",
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
