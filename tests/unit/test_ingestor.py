import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from parallax.ingestion.ingestor import IngestorService
from parallax.shared.schemas import RawMarketData


def _sample_market(market_id="m1") -> RawMarketData:
    return RawMarketData(
        platform="polymarket",
        market_id=market_id,
        title="Test market",
        description="desc",
        resolution_criteria="crit",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )


def _make_session_factory(session):
    @contextmanager
    def factory():
        yield session
    return factory


class TestIngestorService:
    @pytest.mark.anyio
    async def test_run_once_returns_counts_per_platform(self):
        adapter = AsyncMock()
        adapter.platform_name = "polymarket"
        adapter.fetch_markets.return_value = [_sample_market("a"), _sample_market("b")]

        session = MagicMock()
        session.commit = MagicMock()

        with (
            patch("parallax.ingestion.ingestor.MarketRepository") as MockRepo,
            patch("parallax.ingestion.ingestor.AuditService") as MockAudit,
        ):
            mock_repo = MockRepo.return_value
            mock_repo.upsert.return_value = (MagicMock(), True)
            mock_audit = MockAudit.return_value
            mock_audit.record = MagicMock()

            svc = IngestorService([adapter], _make_session_factory(session))
            counts = await svc.run_once()

        assert counts == {"polymarket": 2}

    @pytest.mark.anyio
    async def test_run_once_counts_only_created(self):
        adapter = AsyncMock()
        adapter.platform_name = "polymarket"
        adapter.fetch_markets.return_value = [_sample_market("a"), _sample_market("b")]

        session = MagicMock()
        session.commit = MagicMock()

        with (
            patch("parallax.ingestion.ingestor.MarketRepository") as MockRepo,
            patch("parallax.ingestion.ingestor.AuditService"),
        ):
            mock_repo = MockRepo.return_value
            # First upsert creates, second updates
            mock_repo.upsert.side_effect = [(MagicMock(), True), (MagicMock(), False)]

            svc = IngestorService([adapter], _make_session_factory(session))
            counts = await svc.run_once()

        assert counts == {"polymarket": 1}

    @pytest.mark.anyio
    async def test_run_once_multiple_adapters(self):
        adapter_a = AsyncMock()
        adapter_a.platform_name = "polymarket"
        adapter_a.fetch_markets.return_value = [_sample_market()]

        adapter_b = AsyncMock()
        adapter_b.platform_name = "kalshi"
        adapter_b.fetch_markets.return_value = []

        session = MagicMock()
        session.commit = MagicMock()

        with (
            patch("parallax.ingestion.ingestor.MarketRepository") as MockRepo,
            patch("parallax.ingestion.ingestor.AuditService"),
        ):
            MockRepo.return_value.upsert.return_value = (MagicMock(), True)
            svc = IngestorService([adapter_a, adapter_b], _make_session_factory(session))
            counts = await svc.run_once()

        assert "polymarket" in counts
        assert "kalshi" in counts

    def test_stop_sets_flag(self):
        svc = IngestorService([], _make_session_factory(MagicMock()))
        svc._running = True
        svc.stop()
        assert svc._running is False
