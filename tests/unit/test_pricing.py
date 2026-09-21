"""T009 — web search is billed on top of tokens, at $10 per 1,000 searches."""

from __future__ import annotations

import pytest

from bie.pricing import WEB_SEARCH_COST_PER_SEARCH_USD, cost_usd


def test_verified_price_per_search():
    # https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
    # "Web search is available on the Claude API for $10 per 1,000 searches"
    assert WEB_SEARCH_COST_PER_SEARCH_USD == pytest.approx(0.01)


def test_token_cost_unchanged_without_searches():
    assert cost_usd("claude-opus-5", 1_000_000, 0) == pytest.approx(5.00)
    assert cost_usd("claude-opus-5", 0, 1_000_000) == pytest.approx(25.00)


def test_searches_add_to_token_cost():
    tokens_only = cost_usd("claude-opus-5", 1_000_000, 0)
    with_searches = cost_usd("claude-opus-5", 1_000_000, 0, web_searches=8)
    assert with_searches == pytest.approx(tokens_only + 0.08)


def test_unknown_model_still_bills_searches():
    assert cost_usd("nonexistent-model", 1_000, 1_000, web_searches=3) == pytest.approx(0.03)
