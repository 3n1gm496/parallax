from __future__ import annotations

import asyncio
import uuid

import pytest
from datetime import datetime, timezone

from parallax.db.models import RawMarket
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.divergence.service import DivergenceService
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.ingestion.market_repository import MarketRepository
from parallax.prover.service import ProverService
from parallax.shared.schemas import RawMarketData, RelationType


def _raw_market_data(market_id: str, yes_price: float, group_id: str | None = None) -> RawMarketData:
    return RawMarketData(
        platform="polymarket",
        market_id=market_id,
        title=f"Will {market_id} happen?",
        description="Test market.",
        resolution_criteria="Resolves YES if it happens.",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        group_id=group_id,
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=None,
        raw_payload={},
    )


@pytest.mark.integration
class TestMarketRepositoryIntegration:
    def test_upsert_and_retrieve(self, test_session):
        repo = MarketRepository(test_session)
        data = _raw_market_data("test-upsert-001", 0.6)
        market, created = repo.upsert(data)
        test_session.commit()
        assert created is True
        assert market.id == "polymarket:test-upsert-001"

        retrieved = repo.get("polymarket:test-upsert-001")
        assert retrieved is not None
        assert abs(retrieved.outcome_prices[0] - 0.6) < 0.001

    def test_upsert_updates_existing(self, test_session):
        repo = MarketRepository(test_session)
        data = _raw_market_data("test-upsert-002", 0.5)
        repo.upsert(data)
        test_session.commit()

        updated = _raw_market_data("test-upsert-002", 0.7)
        _, created = repo.upsert(updated)
        test_session.commit()
        assert created is False
        market = repo.get("polymarket:test-upsert-002")
        assert abs(market.outcome_prices[0] - 0.7) < 0.001


@pytest.mark.integration
class TestProverServiceIntegration:
    def _insert_market(self, session, market_id: str, yes_price: float, group_id: str) -> RawMarket:
        repo = MarketRepository(session)
        data = _raw_market_data(market_id, yes_price, group_id)
        market, _ = repo.upsert(data)
        session.commit()
        return market

    def test_stage1_detects_and_stores_relation(self, test_session):
        suffix = uuid.uuid4().hex[:6]
        a = self._insert_market(test_session, f"int-rel-a-{suffix}", 0.6, f"grp-int-{suffix}")
        b = self._insert_market(test_session, f"int-rel-b-{suffix}", 0.55, f"grp-int-{suffix}")
        graph_repo = PostgresGraphRepository(test_session)
        prover = ProverService(test_session, graph_repo, stage2_classifier=None)

        count = asyncio.run(prover.run([a, b]))
        test_session.commit()

        assert count == 1
        assert graph_repo.relation_exists(a.id, b.id, RelationType.MUTUALLY_EXCLUSIVE)


@pytest.mark.integration
class TestDivergenceServiceIntegration:
    def test_scan_creates_candidate(self, test_session):
        repo = MarketRepository(test_session)
        suffix = uuid.uuid4().hex[:6]
        a_data = _raw_market_data(f"div-a-{suffix}", 0.60, f"div-grp-{suffix}")
        b_data = _raw_market_data(f"div-b-{suffix}", 0.55, f"div-grp-{suffix}")
        a, _ = repo.upsert(a_data)
        b, _ = repo.upsert(b_data)
        test_session.commit()

        graph_repo = PostgresGraphRepository(test_session)
        graph_repo.add_relation(a.id, b.id, RelationType.MUTUALLY_EXCLUSIVE, 0.95, {}, "test")
        test_session.commit()

        svc = DivergenceService(test_session, graph_repo, friction_bps=50)
        count = svc.scan([a, b])
        test_session.commit()

        assert count == 1
        cand_repo = CandidateRepository(test_session)
        candidates = cand_repo.list_open()
        assert any(frozenset(c.market_ids) == frozenset([a.id, b.id]) for c in candidates)
