from __future__ import annotations

import asyncio
import uuid

import pytest
from datetime import datetime, timezone

from parallax.api.routes.positions import settle_position
from parallax.audit.repository import AuditRepository
from parallax.autopsy.service import AutopsyService
from parallax.db.models import CompiledContract, CompiledProposition, RawMarket
from parallax.court.service import CourtService
from parallax.candidates.repository import CandidateRepository
from parallax.divergence.service import DivergenceService
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.ingestion.market_repository import MarketRepository
from parallax.prover.service import ProverService
from parallax.shared.schemas import CourtDecision, RawMarketData, RelationType, SettlementRequest
from parallax.tracker.service import TrackerService


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

    def _insert_compilation(self, session, market: RawMarket, *, canonical_object: str) -> None:
        contract = {
            "yes_conditions": [f"{canonical_object} happens"],
            "no_conditions": [f"{canonical_object} does not happen"],
            "exclusions": [],
            "ambiguity_terms": [],
            "counterexamples": [],
            "compiler_confidence": 0.9,
            "canonical_subject": "event",
            "canonical_predicate": "happens_before",
            "canonical_object": canonical_object,
            "temporal_deadline": "2025-12-31T00:00:00+00:00",
            "oracle_focus": "official",
            "proposition_family": "event:happens_before",
            "partition_hint": False,
            "semantic_tags": [],
        }
        proposition = {
            "raw_market_id": market.id,
            "canonical_subject": "event",
            "canonical_predicate": "happens_before",
            "canonical_object": canonical_object,
            "temporal_deadline": "2025-12-31T00:00:00+00:00",
            "oracle_focus": "official",
            "proposition_family": "event:happens_before",
            "partition_hint": False,
            "semantic_tags": [],
            "compiler_confidence": 0.9,
        }
        session.add(
            CompiledContract(
                raw_market_id=market.id,
                contract_json=contract,
                compiler_confidence=0.9,
                compiler_version="test-v1",
            )
        )
        session.add(
            CompiledProposition(
                raw_market_id=market.id,
                proposition_json=proposition,
                compiler_version="test-v1",
            )
        )
        session.commit()

    def test_structural_detector_detects_and_stores_relation(self, test_session):
        suffix = uuid.uuid4().hex[:6]
        a = self._insert_market(test_session, f"int-rel-a-{suffix}", 0.6, f"grp-int-{suffix}")
        b = self._insert_market(test_session, f"int-rel-b-{suffix}", 0.55, f"grp-int-{suffix}")
        self._insert_compilation(test_session, a, canonical_object="candidate-a")
        self._insert_compilation(test_session, b, canonical_object="candidate-b")
        graph_repo = PostgresGraphRepository(test_session)
        prover = ProverService(test_session, graph_repo, semantic_analyzer=None)

        count = asyncio.run(prover.run([a, b]))
        test_session.commit()

        assert count == 1
        assert graph_repo.relation_exists(a.id, b.id, RelationType.SAME_EVENT_FAMILY)


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


@pytest.mark.integration
class TestLifecycleIntegration:
    def test_candidate_flows_through_court_position_and_settlement(self, test_session):
        repo = MarketRepository(test_session)
        suffix = uuid.uuid4().hex[:6]
        group_id = f"life-grp-{suffix}"
        a_data = _raw_market_data(f"life-a-{suffix}", 0.60, group_id)
        b_data = _raw_market_data(f"life-b-{suffix}", 0.55, group_id)
        a, _ = repo.upsert(a_data)
        b, _ = repo.upsert(b_data)
        test_session.commit()

        graph_repo = PostgresGraphRepository(test_session)
        graph_repo.add_relation(a.id, b.id, RelationType.MUTUALLY_EXCLUSIVE, 0.95, {}, "test")
        test_session.commit()

        divergence = DivergenceService(test_session, graph_repo, friction_bps=50)
        assert divergence.scan([a, b]) == 1
        test_session.commit()

        candidate_repo = CandidateRepository(test_session)
        candidate = candidate_repo.list_open(limit=1)[0]

        court = CourtService(test_session)
        assert court.evaluate(str(candidate.id)) == CourtDecision.APPROVED
        test_session.commit()

        refreshed = candidate_repo.get(str(candidate.id))
        assert refreshed is not None
        assert refreshed.court_decision == CourtDecision.APPROVED.value
        snapshot = candidate_repo.get_decision_snapshot(str(candidate.id))
        assert snapshot is not None
        assert snapshot.court_assessment is not None
        assert snapshot.simulation_result is not None
        assert snapshot.snapshot_version == "decision-snapshot-v1"

        tracker = TrackerService(test_session)
        position = tracker.open_position(str(candidate.id))
        assert position is not None
        test_session.commit()

        refreshed = candidate_repo.get(str(candidate.id))
        assert refreshed is not None
        assert refreshed.court_decision == CourtDecision.PAPER_TRADE.value

        record = settle_position(
            position_id=str(position.id),
            payload=SettlementRequest(
                actual_pnl=0.04,
                actual_resolution={a.id: "NO", b.id: "YES"},
                resolution_type="CORRECT",
            ),
            session=test_session,
        )
        test_session.commit()

        assert record.position_id == str(position.id)
        assert record.resolution_type == "CORRECT"
        assert record.labels == []

        settled_position = tracker.get_position(str(position.id))
        assert settled_position is not None
        assert settled_position.status == "CLOSED"
        assert settled_position.actual_pnl == 0.04

        closed_candidate = candidate_repo.get(str(candidate.id))
        assert closed_candidate is not None
        assert closed_candidate.status == "closed"
        assert closed_candidate.resolved_at is not None

        autopsy_rows = AutopsyService(test_session).list_for_candidate(str(candidate.id))
        assert len(autopsy_rows) == 1
        assert autopsy_rows[0].position_id == position.id
        assert autopsy_rows[0].labels == []

        audit_rows = AuditRepository(test_session).list_for_entity("position", str(position.id))
        assert any(row.event_type == "position.settled" for row in audit_rows)
