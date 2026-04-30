"""Smoke tests for CourtService, SimulatorService, AutopsyService stubs."""
import uuid
from unittest.mock import MagicMock
from parallax.db.models import AutopsyRecord, OpportunityCandidate
from parallax.court.service import CourtService
from parallax.simulator.service import SimulatorService
from parallax.autopsy.service import AutopsyService
from parallax.shared.schemas import (
    CourtDecision,
    Leg,
    OpportunityType,
    PayoffMatrix,
    ResolutionType,
    Scenario,
    SimulationResult,
)


def _candidate(worst_case: float) -> OpportunityCandidate:
    matrix = PayoffMatrix(
        legs=[Leg(market_id="pm:a", side="YES", price=0.45, platform="pm")],
        total_cost=0.45,
        scenarios=[Scenario(name="win", description="win", payoff=worst_case, is_breaking=False)],
        worst_case_payoff=worst_case,
        best_case_payoff=worst_case,
        breaking_scenario=None,
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        friction_bps=10,
    )
    cid = uuid.uuid4()
    return OpportunityCandidate(
        id=cid,
        market_ids=["pm:a"],
        payoff_matrix=matrix.model_dump(),
        opportunity_type=OpportunityType.PURE_ARBITRAGE.value,
        worst_case_payoff=worst_case,
        friction_bps=10,
        risk_scores={},
        court_decision=CourtDecision.PENDING.value,
    )


class TestCourtService:
    def test_positive_payoff_gets_approved(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = CourtService(session)
        decision = svc.evaluate(str(c.id))
        assert decision == CourtDecision.APPROVED

    def test_zero_payoff_gets_watchlisted(self):
        session = MagicMock()
        session.flush = MagicMock()
        c = _candidate(0.0)
        session.get.return_value = c
        svc = CourtService(session)
        decision = svc.evaluate(str(c.id))
        assert decision == CourtDecision.WATCHLIST


class TestSimulatorService:
    def test_simulate_returns_result(self):
        session = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = SimulatorService(session)
        result = svc.simulate(str(c.id))
        assert isinstance(result, SimulationResult)
        assert result.fill_probability == 1.0
        assert result.note == "stub — no order book model"
        assert result.candidate_id == str(c.id)

    def test_simulate_executable_when_positive_pnl(self):
        session = MagicMock()
        c = _candidate(0.05)
        session.get.return_value = c
        svc = SimulatorService(session)
        result = svc.simulate(str(c.id))
        assert result.is_executable is True


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
