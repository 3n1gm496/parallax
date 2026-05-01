import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from parallax.ingestion.polymarket_adapter import PolymarketAdapter


def _raw_market(market_id="m1", end_date="2025-12-31T00:00:00Z", closed=False, **kwargs):
    base = {
        "id": market_id,
        "question": "Will X happen?",
        "description": "Some description",
        "resolutionSource": "oracle.com",
        "endDate": end_date,
        "closed": closed,
        "category": "politics",
        "eventId": "event-1",
        "tokens": [
            {"outcome": "Yes", "price": 0.6},
            {"outcome": "No", "price": 0.4},
        ],
    }
    base.update(kwargs)
    return base


class TestPolymarketAdapter:
    def test_platform_name(self):
        assert PolymarketAdapter().platform_name == "polymarket"

    def test_parse_valid_market(self):
        adapter = PolymarketAdapter()
        raw = _raw_market()
        result = adapter._parse(raw)

        assert result is not None
        assert result.platform == "polymarket"
        assert result.market_id == "m1"
        assert result.title == "Will X happen?"
        assert result.outcomes == ["Yes", "No"]
        assert result.outcome_prices == [0.6, 0.4]
        assert result.is_closed is False
        assert result.deadline == datetime(2025, 12, 31, tzinfo=timezone.utc)
        assert result.group_id == "event-1"

    def test_parse_missing_end_date_returns_none(self):
        adapter = PolymarketAdapter()
        raw = _raw_market()
        del raw["endDate"]
        assert adapter._parse(raw) is None

    def test_parse_missing_id_returns_none(self):
        adapter = PolymarketAdapter()
        raw = _raw_market()
        del raw["id"]
        assert adapter._parse(raw) is None

    def test_parse_missing_token_price_defaults_to_zero(self):
        adapter = PolymarketAdapter()
        raw = _raw_market()
        raw["tokens"] = [{"outcome": "Yes", "price": None}, {"outcome": "No", "price": 0.4}]
        result = adapter._parse(raw)
        assert result is not None
        assert result.outcome_prices == [0.0, 0.4]

    @pytest.mark.anyio
    async def test_fetch_markets_paginates(self):
        adapter = PolymarketAdapter(max_events=3)
        batch1 = [_raw_market(market_id=str(i)) for i in range(3)]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = batch1

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        adapter._client = mock_client
        markets = await adapter.fetch_markets()
        assert len(markets) == 3

    @pytest.mark.anyio
    async def test_fetch_markets_stops_on_empty_batch(self):
        adapter = PolymarketAdapter(max_events=100)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        adapter._client = mock_client
        markets = await adapter.fetch_markets()
        assert markets == []
