"""Smoke tests for CourtService, SimulatorService, and AutopsyService core lifecycle paths."""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
from parallax.db.models import RawMarket
from parallax.db.models import OpportunityCandidate
from parallax.court.service import CourtService
from parallax.simulator.service import SimulatorService
from parallax.autopsy.service import AutopsyService
from parallax.shared.schemas import (
    CourtAssessment,
    CourtDecision,
    Leg,
    OpportunityType,
    PayoffMatrix,
    ResolutionType,
    RiskScore,
    RelationType,
    Scenario,
    SimulationResult,
)


def _candidate(
    worst_case: float,
    *,
    opportunity_type: OpportunityType = OpportunityType.PURE_ARBITRAGE,
    market_ids: list[str] | None = None,
    risk_scores: dict | None = None,
) -> OpportunityCandidate:
    matrix = PayoffMatrix(
        legs=[Leg(market_id="pm:a", side="YES", price=0.45, platform="pm")],
        total_cost=0.45,
        scenarios=[Scenario(name="win", description="win", payoff=worst_case, is_breaking=False)],
        worst_case_payoff=worst_case,
        best_case_payoff=worst_case,
        breaking_scenario=None,
        opportunity_type=opportunity_type,
        friction_bps=10,
    )
    cid = uuid.uuid4()
    return OpportunityCandidate(
        id=cid,
        market_ids=market_ids or ["pm:a"],
        payoff_matrix=matrix.model_dump(),
        opportunity_type=opportunity_type.value,
        worst_case_payoff=worst_case,
        friction_bps=10,
        risk_scores=risk_scores or RiskScore.combine(oracle=0.1, deadline=0.1, semantic=0.1).model_dump(),
        court_decision=CourtDecision.PENDING.value,
    )

def _market(mid: str, source: str | None = None) -> RawMarket:
    return RawMarket(
        id=mid,
        platform=mid.split(":")[0],
        market_id=mid.split(":")[-1],
        title=mid,
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[0.45, 0.55],
        group_id=None,
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=source,
        raw_payload={},
    )


class TestCourtService:
    def test_positive_payoff_gets_approved(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(return_value=None)
        svc._graph_repo.get_relations = MagicMock(return_value=[])
        decision = svc.evaluate(str(c.id))
        assert decision == CourtDecision.APPROVED

    def test_zero_payoff_gets_watchlisted(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(0.0)
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(return_value=None)
        svc._graph_repo.get_relations = MagicMock(return_value=[])
        decision = svc.evaluate(str(c.id))
        assert decision == CourtDecision.REJECTED

    def test_negative_payoff_gets_rejected(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(-0.01)
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(return_value=None)
        svc._graph_repo.get_relations = MagicMock(return_value=[])
        decision = svc.evaluate(str(c.id))
        assert decision == CourtDecision.REJECTED

    def test_assess_returns_reasons(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(return_value=None)
        svc._graph_repo.get_relations = MagicMock(return_value=[])
        assessment = svc.assess(str(c.id))
        assert isinstance(assessment, CourtAssessment)
        assert assessment.reasons
        assert assessment.gates

    def test_evaluate_persists_decision_snapshot(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(0.05, market_ids=["pm:a", "pm:b"])
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(return_value=None)
        svc._graph_repo.get_relations = MagicMock(return_value=[])
        persisted = {}

        def _capture_snapshot(candidate_id, **kwargs):
            persisted["candidate_id"] = candidate_id
            persisted["kwargs"] = kwargs
            return MagicMock()

        svc._repo.upsert_decision_snapshot = MagicMock(side_effect=_capture_snapshot)
        decision = svc.evaluate(str(c.id), run_id="run-123")

        assert decision == CourtDecision.APPROVED
        assert persisted["candidate_id"] == str(c.id)
        assert persisted["kwargs"]["run_id"] == "run-123"
        assert persisted["kwargs"]["simulation_result"] is not None
        assert persisted["kwargs"]["court_assessment"] is not None

    def test_duplicate_divergence_with_oracle_mismatch_gets_rejected(self):
        session = MagicMock()
        c = _candidate(
            0.05,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            market_ids=["pm:a", "kalshi:b"],
        )
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(side_effect=[_market("pm:a", "polymarket"), _market("kalshi:b", "kalshi")])
        svc._graph_repo.get_relations = MagicMock(return_value=[{
            "from_market_id": "pm:a",
            "to_market_id": "kalshi:b",
            "relation_type": RelationType.EQUIVALENT.value,
            "confidence": 0.92,
            "identity_status": "verified",
            "evidence": {"semantic_confidence": 0.92, "breaking_scenarios": [], "identity_status": "verified"},
        }])
        assessment = svc.assess(str(c.id))
        assert assessment.decision == CourtDecision.REJECTED
        assert "oracle mismatch" in " ".join(assessment.reasons)

    def test_semantic_breaking_scenarios_get_rejected(self):
        session = MagicMock()
        c = _candidate(
            0.05,
            opportunity_type=OpportunityType.SEMANTIC_ARBITRAGE,
            market_ids=["pm:a", "pm:b"],
        )
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(side_effect=[_market("pm:a", "same"), _market("pm:b", "same")])
        svc._graph_repo.get_relations = MagicMock(return_value=[{
            "from_market_id": "pm:a",
            "to_market_id": "pm:b",
            "relation_type": RelationType.SUBSET.value,
            "confidence": 0.88,
            "identity_status": "verified",
            "evidence": {
                "semantic_confidence": 0.88,
                "identity_status": "verified",
                "breaking_scenarios": [{"scenario_description": "late deadline", "resolution_a": "YES", "resolution_b": "NO", "why_different": "deadline drift"}],
            },
        }])
        assessment = svc.assess(str(c.id))
        assert assessment.decision == CourtDecision.REJECTED
        assert "breaking scenarios" in " ".join(assessment.reasons)

    def test_duplicate_divergence_with_low_relation_confidence_gets_watchlisted(self):
        session = MagicMock()
        c = _candidate(
            0.05,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            market_ids=["pm:a", "pm:b"],
            risk_scores=RiskScore.combine(oracle=0.05, deadline=0.05, semantic=0.05).model_dump(),
        )
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(side_effect=[_market("pm:a", "same"), _market("pm:b", "same")])
        svc._graph_repo.get_relations = MagicMock(return_value=[{
            "from_market_id": "pm:a",
            "to_market_id": "pm:b",
            "relation_type": RelationType.DUPLICATE.value,
            "confidence": 0.6,
            "proof_status": "verified",
            "tradeable_relation": True,
            "identity_status": "verified",
            "evidence": {
                "semantic_confidence": 0.6,
                "breaking_scenarios": [],
                "proof_status": "verified",
                "tradeable_relation": True,
                "identity_status": "verified",
            },
        }])
        assessment = svc.assess(str(c.id))
        assert assessment.decision == CourtDecision.WATCHLIST
        assert "relation confidence" in " ".join(assessment.reasons)

    def test_semantic_deadline_mismatch_gets_rejected(self):
        session = MagicMock()
        c = _candidate(
            0.05,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            market_ids=["pm:a", "pm:b"],
            risk_scores=RiskScore.combine(oracle=0.05, deadline=0.05, semantic=0.05).model_dump(),
        )
        session.get.return_value = c
        svc = CourtService(session)
        svc._market_repo.get = MagicMock(side_effect=[_market("pm:a", "same"), _market("pm:b", "same")])
        svc._graph_repo.get_relations = MagicMock(return_value=[{
            "from_market_id": "pm:a",
            "to_market_id": "pm:b",
            "relation_type": RelationType.DUPLICATE.value,
            "confidence": 0.92,
            "identity_status": "verified",
            "evidence": {
                "semantic_confidence": 0.92,
                "identity_status": "verified",
                "breaking_scenarios": [],
                "relation_signals": {"deadline_mismatch": True, "oracle_mismatch": False, "ambiguity_level": "low"},
            },
        }])
        assessment = svc.assess(str(c.id))
        assert assessment.decision == CourtDecision.REJECTED
        assert "deadline drift" in " ".join(assessment.reasons)


class TestSimulatorService:
    def test_simulate_returns_result(self):
        session = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = SimulatorService(session)
        result = svc.simulate(str(c.id))
        assert isinstance(result, SimulationResult)
        assert 0.2 <= result.fill_probability <= 1.0
        assert "venue-aware execution model" in result.note
        assert result.candidate_id == str(c.id)
        assert result.estimated_slippage_bps >= 0
        assert result.model_version == "heuristic-v3"
        assert result.displayed_edge >= result.executable_edge
        assert result.spread_cross_cost >= 0
        assert result.partial_fill_cost >= 0

    def test_simulate_applies_small_execution_drag(self):
        session = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = SimulatorService(session)
        result = svc.simulate(str(c.id))
        assert result.simulated_pnl < 0.05
        assert result.executable_edge == result.simulated_pnl
        assert result.is_executable is True

    def test_simulate_not_executable_when_payoff_zero(self):
        session = MagicMock()
        c = _candidate(0.0)
        session.get.return_value = c
        svc = SimulatorService(session)
        result = svc.simulate(str(c.id))
        assert result.is_executable is False

    def test_simulate_penalizes_relation_mismatch_signals(self):
        session = MagicMock()
        c = _candidate(
            0.05,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            market_ids=["pm:a", "kalshi:b"],
            risk_scores=RiskScore.combine(oracle=0.05, deadline=0.05, semantic=0.05).model_dump(),
        )
        session.get.return_value = c
        svc = SimulatorService(session)
        svc._graph_repo.get_relations = MagicMock(return_value=[])
        baseline = svc.simulate(str(c.id))
        svc._graph_repo.get_relations = MagicMock(return_value=[{
            "from_market_id": "pm:a",
            "to_market_id": "kalshi:b",
            "relation_type": RelationType.EQUIVALENT.value,
            "confidence": 0.9,
            "evidence": {
                "relation_signals": {
                    "oracle_mismatch": True,
                    "deadline_mismatch": True,
                    "ambiguity_level": "high",
                }
            },
        }])
        result = svc.simulate(str(c.id))
        assert result.simulated_pnl < baseline.simulated_pnl
        assert result.fill_probability < baseline.fill_probability

    def test_cross_platform_execution_has_higher_spread_cross_cost(self):
        session = MagicMock()
        same_platform = _candidate(0.05, market_ids=["pm:a", "pm:b"])
        cross_platform = _candidate(0.05, market_ids=["pm:a", "kalshi:b"])
        same_platform.payoff_matrix["legs"] = [
            {"market_id": "pm:a", "side": "YES", "price": 0.45, "platform": "pm"},
            {"market_id": "pm:b", "side": "NO", "price": 0.55, "platform": "pm"},
        ]
        cross_platform.payoff_matrix["legs"] = [
            {"market_id": "pm:a", "side": "YES", "price": 0.45, "platform": "pm"},
            {"market_id": "kalshi:b", "side": "NO", "price": 0.55, "platform": "kalshi"},
        ]
        svc = SimulatorService(session)

        session.get.return_value = same_platform
        same_result = svc.simulate(str(same_platform.id))
        session.get.return_value = cross_platform
        cross_result = svc.simulate(str(cross_platform.id))

        assert cross_result.spread_cross_cost > same_result.spread_cross_cost


class TestAutopsyService:
    def test_record_creates_autopsy_record(self):
        session = MagicMock()
        session.flush = MagicMock()
        svc = AutopsyService(session)
        candidate_id = str(uuid.uuid4())
        record = svc.record(
            candidate_id=candidate_id,
            actual_resolution={"pm:a": "YES"},
            resolution_type=ResolutionType.CORRECT,
        )
        assert record.resolution_type == ResolutionType.CORRECT.value
        assert record.identity_error is False
        session.add.assert_called_once_with(record)
        session.get.assert_called()

    def test_identity_error_sets_flag(self):
        session = MagicMock()
        session.flush = MagicMock()
        svc = AutopsyService(session)
        record = svc.record(
            candidate_id=str(uuid.uuid4()),
            actual_resolution={"pm:a": "YES"},
            resolution_type=ResolutionType.IDENTITY_ERROR,
        )
        assert record.identity_error is True
