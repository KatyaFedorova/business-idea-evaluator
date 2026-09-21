"""Token pricing so every run reports what it actually cost.

Prices are USD per million tokens, first-party Anthropic API rates.
"""

from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    # model id: (input $/MTok, output $/MTok)
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Web search is billed on top of tokens: $10 per 1,000 searches on the Claude API.
# Errors are not billed. Verified 2026-09-21 against
# https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
WEB_SEARCH_COST_PER_SEARCH_USD = 10.0 / 1000

# Cached input is billed at a fraction of the base input rate.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    web_searches: int = 0,
) -> float:
    """Dollar cost of one request, tokens plus server-tool use.

    An unknown model contributes no token cost rather than crashing a run, but its
    searches are still billed, because those are priced per search and not per model.
    """
    search_cost = web_searches * WEB_SEARCH_COST_PER_SEARCH_USD
    if model not in PRICES:
        return search_cost
    in_rate, out_rate = PRICES[model]
    return search_cost + (
        input_tokens * in_rate
        + cache_write_tokens * in_rate * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * in_rate * CACHE_READ_MULTIPLIER
        + output_tokens * out_rate
    ) / 1_000_000
