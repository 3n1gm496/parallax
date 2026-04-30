from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from parallax.ingestion.market_repository import MarketRepository
from parallax.db.models import RawMarket
from parallax.shared.schemas import RawMarketData


def _sample_data(**overrides) -> RawMarketData:
    base = dict(
        platform="polymarket",
        market_id="abc123",
        title="Will X happen?",
        description="desc",
        resolution_criteria="crit",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
        category=None,
        group_id="g1",
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=None,
        raw_payload={"raw": True},
    )
    base.update(overrides)
    return RawMarketData(**base)


class TestMarketRepository:
    def test_upsert_creates_new_market(self):
        session = MagicMock()
        session.get.return_value = None
        repo = MarketRepository(session)

        market, created = repo.upsert(_sample_data())

        assert created is True
        assert market.id == "polymarket:abc123"
        assert market.platform == "polymarket"
        session.add.assert_called_once_with(market)

    def test_upsert_updates_existing_market(self):
        session = MagicMock()
        existing = RawMarket(
            id="polymarket:abc123",
            platform="polymarket",
            market_id="abc123",
            title="old title",
            description="old desc",
            resolution_criteria="old crit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.5, 0.5],
            category=None,
            group_id=None,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            is_closed=False,
            resolution_source=None,
            raw_payload={},
        )
        session.get.return_value = existing
        repo = MarketRepository(session)

        updated_data = _sample_data(title="new title", outcome_prices=[0.7, 0.3])
        market, created = repo.upsert(updated_data)

        assert created is False
        assert market is existing
        assert market.title == "new title"
        assert market.outcome_prices == [0.7, 0.3]
        session.add.assert_not_called()

    def test_composite_id_format(self):
        session = MagicMock()
        session.get.return_value = None
        repo = MarketRepository(session)

        market, _ = repo.upsert(_sample_data(platform="kalshi", market_id="xyz"))
        assert market.id == "kalshi:xyz"

    def test_get_delegates_to_session(self):
        session = MagicMock()
        session.get.return_value = None
        repo = MarketRepository(session)
        repo.get("polymarket:abc123")
        session.get.assert_called_with(RawMarket, "polymarket:abc123")

    def test_list_open_filters_closed(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = []
        repo = MarketRepository(session)
        repo.list_open()
        session.query.return_value.filter_by.assert_called_with(is_closed=False)

    def test_list_open_with_platform_applies_second_filter(self):
        session = MagicMock()
        chain = session.query.return_value.filter_by.return_value
        chain.filter_by.return_value.all.return_value = []
        repo = MarketRepository(session)
        repo.list_open(platform="polymarket")
        chain.filter_by.assert_called_with(platform="polymarket")

    def test_list_by_group(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = []
        repo = MarketRepository(session)
        repo.list_by_group("g1")
        session.query.return_value.filter_by.assert_called_with(group_id="g1", is_closed=False)
