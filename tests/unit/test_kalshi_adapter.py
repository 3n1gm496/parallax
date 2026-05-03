from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from parallax.ingestion.kalshi_adapter import KalshiAdapter


def _event(event_ticker: str = "KXNEWPOPE-70") -> dict:
    return {
        "event_ticker": event_ticker,
        "category": "World",
        "sub_title": "Before 2070",
        "title": "Who will the next Pope be?",
    }


def _market(ticker: str = "KXNEWPOPE-70-MZUP") -> dict:
    return {
        "ticker": ticker,
        "event_ticker": "KXNEWPOPE-70",
        "market_type": "binary",
        "status": "active",
        "expiration_time": "2070-01-01T15:00:00Z",
        "rules_primary": "If Matteo Zuppi becomes Pope, market resolves Yes.",
        "yes_sub_title": "Matteo Zuppi",
        "yes_bid_dollars": "0.0400",
        "yes_ask_dollars": "0.0600",
    }


def test_platform_name():
    assert KalshiAdapter().platform_name == "kalshi"


def test_parse_market_maps_supported_payload():
    result = KalshiAdapter()._parse_market(_event(), _market())
    assert result is not None
    assert result.platform == "kalshi"
    assert result.market_id == "KXNEWPOPE-70-MZUP"
    assert result.group_id == "KXNEWPOPE-70"
    assert result.outcome_prices == [0.05, 0.95]
    assert result.deadline == datetime(2070, 1, 1, 15, 0, tzinfo=timezone.utc)


def test_parse_market_filters_multivariate_products():
    raw = _market()
    raw["mve_collection_ticker"] = "KXMVE-123"
    assert KalshiAdapter()._parse_market(_event(), raw) is None


@pytest.mark.anyio
async def test_fetch_markets_reads_event_detail_payloads():
    list_response = MagicMock()
    list_response.raise_for_status = MagicMock()
    list_response.json.return_value = {"events": [_event()], "cursor": ""}

    detail_response = MagicMock()
    detail_response.raise_for_status = MagicMock()
    detail_response.json.return_value = {"event": _event(), "markets": [_market()]}

    client = MagicMock()
    client.get = AsyncMock(side_effect=[list_response, detail_response])

    results = await KalshiAdapter(max_events=5, http_client=client).fetch_markets()

    assert [market.market_id for market in results] == ["KXNEWPOPE-70-MZUP"]


@pytest.mark.anyio
async def test_fetch_markets_retries_transient_connect_error():
    list_response = MagicMock()
    list_response.raise_for_status = MagicMock()
    list_response.json.return_value = {"events": [_event()], "cursor": ""}

    detail_response = MagicMock()
    detail_response.raise_for_status = MagicMock()
    detail_response.json.return_value = {"event": _event(), "markets": [_market()]}

    request = httpx.Request("GET", "https://api.elections.kalshi.com/trade-api/v2/events")
    client = MagicMock()
    client.get = AsyncMock(side_effect=[httpx.ConnectError("dns", request=request), list_response, detail_response])

    results = await KalshiAdapter(max_events=5, http_client=client).fetch_markets()

    assert [market.market_id for market in results] == ["KXNEWPOPE-70-MZUP"]
    assert client.get.await_count == 3
