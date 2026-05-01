from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, MagicMock

from parallax.ingestion.kalshi_adapter import KalshiAdapter


def _raw_market(ticker="TRUMP-2026", close_time="2026-01-20T00:00:00Z",
                yes_bid=0.60, yes_ask=0.62, event_ticker="TRUMP-PRES",
                title="Will Trump be president in 2026?") -> dict:
    return {
        "ticker": ticker,
        "title": title,
        "close_time": close_time,
        "status": "open",
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": 1 - yes_ask,
        "no_ask": 1 - yes_bid,
        "event_ticker": event_ticker,
        "category": "Politics",
        "rules_primary": "Resolves YES if Trump is president on Jan 20 2026.",
    }


class TestKalshiAdapter:
    def test_platform_name(self):
        adapter = KalshiAdapter(api_key="test")
        assert adapter.platform_name == "kalshi"

    def test_parse_valid_market(self):
        adapter = KalshiAdapter(api_key="test")
        raw = _raw_market()
        result = adapter._parse(raw)
        assert result is not None
        assert result.platform == "kalshi"
        assert result.market_id == "TRUMP-2026"
        assert result.group_id == "TRUMP-PRES"
        assert abs(result.outcome_prices[0] - 0.61) < 0.01  # mid-price
        assert result.is_closed is False

    def test_parse_closed_market_returns_none(self):
        adapter = KalshiAdapter(api_key="test")
        raw = _raw_market()
        raw["status"] = "finalized"
        result = adapter._parse(raw)
        assert result is None

    def test_parse_missing_close_time_returns_none(self):
        adapter = KalshiAdapter(api_key="test")
        raw = _raw_market()
        del raw["close_time"]
        result = adapter._parse(raw)
        assert result is None

    @pytest.mark.anyio
    async def test_fetch_markets_sends_auth_header(self):
        adapter = KalshiAdapter(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"markets": [_raw_market()], "cursor": ""}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        adapter._client = mock_client

        results = await adapter.fetch_markets()

        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_fetch_markets_paginates_via_cursor(self):
        adapter = KalshiAdapter(api_key="test-key")
        page1 = MagicMock()
        page1.json.return_value = {"markets": [_raw_market("M1")], "cursor": "next-cursor"}
        page1.raise_for_status = MagicMock()
        page2 = MagicMock()
        page2.json.return_value = {"markets": [_raw_market("M2")], "cursor": ""}
        page2.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[page1, page2])
        adapter._client = mock_client

        results = await adapter.fetch_markets()
        assert len(results) == 2
        assert mock_client.get.call_count == 2
