from __future__ import annotations
import json
import os

import httpx
import pytest

from parallax.execution.clob_adapter import PolymarketCLOBAdapter
from parallax.execution.kalshi_quote_adapter import KalshiQuoteAdapter
from parallax.execution.schemas import OrderbookSnapshot


def _assert_snapshot_shape(snap: OrderbookSnapshot) -> None:
    assert snap.platform in {"polymarket", "kalshi"}
    assert isinstance(snap.bids.levels, list)
    assert isinstance(snap.asks.levels, list)
    if snap.mid_price is not None:
        assert 0.0 < snap.mid_price < 1.0, f"mid_price={snap.mid_price} out of (0,1)"
    if snap.spread_bps is not None:
        assert snap.spread_bps >= 0.0


@pytest.mark.anyio
async def test_polymarket_clob_fetch_live():
    """
    Dynamically resolve a live Polymarket market via Gamma API, then fetch its CLOB book.
    Verifies: snapshot is not None, shape is valid, mid_price is in (0, 1).
    """
    gamma_url = "https://gamma-api.polymarket.com/markets"
    params = {"active": "true", "closed": "false", "limit": 1}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(gamma_url, params=params)

    assert resp.status_code == 200, f"Gamma API returned {resp.status_code}"
    markets = resp.json()
    assert isinstance(markets, list) and len(markets) > 0, "No active markets returned"

    market = markets[0]
    # Gamma API returns clobTokenIds and outcomes as JSON-encoded strings
    raw_token_ids = market.get("clobTokenIds") or "[]"
    raw_outcomes = market.get("outcomes") or "[]"
    clob_token_ids = json.loads(raw_token_ids) if isinstance(raw_token_ids, str) else raw_token_ids
    outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes

    assert len(clob_token_ids) > 0, f"No clobTokenIds in market: {market.get('id')}"
    assert len(outcomes) > 0, f"No outcomes in market: {market.get('id')}"

    token_id = clob_token_ids[0]
    outcome = outcomes[0]
    market_id = market.get("id") or market.get("conditionId") or "unknown"

    adapter = PolymarketCLOBAdapter(timeout=8.0)
    snap = await adapter.fetch_snapshot(
        market_id=str(market_id),
        outcome=str(outcome),
        token_id=str(token_id),
    )

    assert snap is not None, (
        f"fetch_snapshot returned None for token_id={token_id!r}. "
        "Check CLOB API reachability or token ID format."
    )
    _assert_snapshot_shape(snap)
    assert snap.platform == "polymarket"
    assert snap.token_id == str(token_id)


@pytest.mark.anyio
async def test_kalshi_orderbook_fetch_live():
    """
    Attempt to fetch a known Kalshi market orderbook.
    Without API key, the adapter returns None gracefully (expected on auth-required endpoints).
    With KALSHI_API_KEY set, verifies full snapshot shape.
    """
    ticker = os.environ.get("SMOKE_KALSHI_TICKER", "KXFED-25MAY07-B5.25")
    api_key = os.environ.get("KALSHI_API_KEY", "")

    adapter = KalshiQuoteAdapter(timeout=8.0, api_key=api_key)
    snap = await adapter.fetch_snapshot(market_id=ticker, outcome="YES")

    if api_key:
        assert snap is not None, (
            f"fetch_snapshot returned None for ticker={ticker!r} even with KALSHI_API_KEY set. "
            "Check ticker validity or API key scope."
        )
        _assert_snapshot_shape(snap)
        assert snap.platform == "kalshi"
    else:
        # Without credentials: graceful None is the correct behavior (401 → None).
        # If the Kalshi elections endpoint happens to be public, a snapshot is also acceptable.
        assert snap is None or isinstance(snap, OrderbookSnapshot), (
            "fetch_snapshot must return None or OrderbookSnapshot, never raise"
        )
        if snap is not None:
            _assert_snapshot_shape(snap)
