from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx

from parallax.execution.clob_adapter import PolymarketCLOBAdapter, _parse_side, _mid_price, _spread_bps
from parallax.execution.schemas import OrderbookSide, OrderbookLevel


def _mock_client(status: int = 200, json_body: dict | None = None) -> httpx.AsyncClient:
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = status
    response.json.return_value = json_body or {}
    client.get.return_value = response
    client.aclose = AsyncMock()
    return client


@pytest.mark.anyio
async def test_fetch_snapshot_returns_snapshot():
    body = {
        "bids": [{"price": "0.45", "size": "100"}, {"price": "0.44", "size": "50"}],
        "asks": [{"price": "0.46", "size": "80"}],
    }
    client = _mock_client(200, body)
    adapter = PolymarketCLOBAdapter(http_client=client)
    snap = await adapter.fetch_snapshot("0xabc", "YES", "tok-123")

    assert snap is not None
    assert snap.platform == "polymarket"
    assert snap.market_id == "0xabc"
    assert snap.outcome == "YES"
    assert len(snap.bids.levels) == 2
    assert len(snap.asks.levels) == 1
    assert snap.mid_price == pytest.approx(0.455)


@pytest.mark.anyio
async def test_fetch_snapshot_returns_none_on_non_200():
    client = _mock_client(404)
    adapter = PolymarketCLOBAdapter(http_client=client)
    snap = await adapter.fetch_snapshot("0xabc", "YES", "tok-123")
    assert snap is None


@pytest.mark.anyio
async def test_fetch_snapshot_returns_none_on_exception():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("refused")
    client.aclose = AsyncMock()
    adapter = PolymarketCLOBAdapter(http_client=client)
    snap = await adapter.fetch_snapshot("0xabc", "YES", "tok-123")
    assert snap is None


def test_parse_side_skips_invalid():
    levels = [
        {"price": "0.45", "size": "100"},
        {"price": "0", "size": "50"},     # zero price → skip
        {"price": "bad", "size": "50"},   # invalid → skip
    ]
    side = _parse_side(levels)
    assert len(side.levels) == 1
    assert side.levels[0].price == pytest.approx(0.45)


def test_mid_price():
    bids = OrderbookSide(levels=[OrderbookLevel(price=0.45, size=100)])
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.46, size=80)])
    assert _mid_price(bids, asks) == pytest.approx(0.455)


def test_mid_price_empty_returns_none():
    bids = OrderbookSide()
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.46, size=80)])
    assert _mid_price(bids, asks) is None


def test_spread_bps():
    bids = OrderbookSide(levels=[OrderbookLevel(price=0.45, size=100)])
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.46, size=80)])
    expected = ((0.46 - 0.45) / 0.45) * 10000
    assert _spread_bps(bids, asks) == pytest.approx(expected)
