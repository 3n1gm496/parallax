from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx

from parallax.execution.kalshi_quote_adapter import (
    KalshiQuoteAdapter,
    _parse_kalshi_sides,
    _parse_cents_side,
)
from parallax.execution.schemas import OrderbookSide


def _mock_client(status: int = 200, json_body: dict | None = None) -> httpx.AsyncClient:
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = status
    response.json.return_value = json_body or {}
    client.get.return_value = response
    client.aclose = AsyncMock()
    return client


@pytest.mark.anyio
async def test_fetch_snapshot_yes_outcome():
    body = {
        "orderbook": {
            "yes": [[55, 100], [54, 50]],
            "no": [[46, 80]],
        }
    }
    client = _mock_client(200, body)
    adapter = KalshiQuoteAdapter(http_client=client)
    snap = await adapter.fetch_snapshot("KXTEST-24", "YES")

    assert snap is not None
    assert snap.platform == "kalshi"
    assert snap.outcome == "YES"
    assert len(snap.bids.levels) == 2
    assert snap.bids.levels[0].price == pytest.approx(0.55)
    # NO bid at 46 → YES ask at 0.54
    assert len(snap.asks.levels) == 1
    assert snap.asks.levels[0].price == pytest.approx(0.54)


@pytest.mark.anyio
async def test_fetch_snapshot_returns_none_on_404():
    client = _mock_client(404)
    adapter = KalshiQuoteAdapter(http_client=client)
    snap = await adapter.fetch_snapshot("KXTEST-24", "YES")
    assert snap is None


@pytest.mark.anyio
async def test_fetch_snapshot_returns_none_on_exception():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("refused")
    client.aclose = AsyncMock()
    adapter = KalshiQuoteAdapter(http_client=client)
    snap = await adapter.fetch_snapshot("KXTEST-24", "YES")
    assert snap is None


def test_parse_cents_side_basic():
    side = _parse_cents_side([[55, 100], [54, 50], [0, 10]])  # 0 cents → skip
    assert len(side.levels) == 2
    assert side.levels[0].price == pytest.approx(0.55)


def test_parse_kalshi_sides_yes():
    data = {"yes": [[60, 200]], "no": [[45, 100]]}
    bids, asks = _parse_kalshi_sides(data, "YES")
    assert bids.levels[0].price == pytest.approx(0.60)
    # NO bid at 45 → YES ask at 0.55
    assert asks.levels[0].price == pytest.approx(0.55)


def test_parse_kalshi_sides_no():
    data = {"yes": [[60, 200]], "no": [[45, 100]]}
    bids, asks = _parse_kalshi_sides(data, "NO")
    assert bids.levels[0].price == pytest.approx(0.45)
    # YES bid at 60 → NO ask at 0.40
    assert asks.levels[0].price == pytest.approx(0.40)


def test_parse_kalshi_sides_empty():
    bids, asks = _parse_kalshi_sides({}, "YES")
    assert bids.levels == []
    assert asks.levels == []


@pytest.mark.anyio
async def test_fetch_snapshot_sends_auth_header_when_key_set():
    body = {
        "orderbook": {
            "yes": [[55, 100]],
            "no": [[46, 80]],
        }
    }
    client = _mock_client(200, body)
    adapter = KalshiQuoteAdapter(http_client=client, api_key="test-key-abc")
    await adapter.fetch_snapshot("KXTEST-24", "YES")

    call_kwargs = client.get.call_args[1]
    assert "headers" in call_kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key-abc"


@pytest.mark.anyio
async def test_fetch_snapshot_no_auth_header_when_key_empty():
    body = {
        "orderbook": {
            "yes": [[55, 100]],
            "no": [],
        }
    }
    client = _mock_client(200, body)
    adapter = KalshiQuoteAdapter(http_client=client, api_key="")
    await adapter.fetch_snapshot("KXTEST-24", "YES")

    call_kwargs = client.get.call_args[1]
    headers = call_kwargs.get("headers", {})
    assert "Authorization" not in headers
