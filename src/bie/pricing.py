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

# Cached input is billed at a fraction of the base input rate.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Dollar cost of one request. Unknown models cost 0.0 rather than crashing a run."""
    if model not in PRICES:
        return 0.0
    in_rate, out_rate = PRICES[model]
    return (
        input_tokens * in_rate
        + cache_write_tokens * in_rate * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * in_rate * CACHE_READ_MULTIPLIER
        + output_tokens * out_rate
    ) / 1_000_000
