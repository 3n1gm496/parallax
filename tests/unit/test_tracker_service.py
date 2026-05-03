import uuid
from unittest.mock import MagicMock
from parallax.config import settings
from parallax.db.models import OpportunityCandidate, PaperPosition
from parallax.tracker.service import TrackerService
from parallax.shared.schemas import CourtDecision, Leg, OpportunityType, PayoffMatrix, Scenario


def _payoff_matrix() -> PayoffMatrix:
    return PayoffMatrix(
        legs=[Leg(market_id="pm:a", side="YES", price=0.45, platform="pm")],
        total_cost=0.45,
        scenarios=[Scenario(name="YES", description="wins", payoff=0.05, is_breaking=False)],
        worst_case_payoff=0.05,
        best_case_payoff=0.05,
        breaking_scenario=None,
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        friction_bps=10,
    )


def _candidate(candidate_id: uuid.UUID) -> OpportunityCandidate:
    m = _payoff_matrix()
    return OpportunityCandidate(
        id=candidate_id,
        market_ids=["pm:a", "kalshi:b"],
        payoff_matrix=m.model_dump(),
        opportunity_type=OpportunityType.PURE_ARBITRAGE.value,
        worst_case_payoff=0.05,
        friction_bps=10,
        risk_scores={},
        court_decision=CourtDecision.APPROVED.value,
    )


class TestTrackerService:
    def test_open_position_creates_record(self):
        session = MagicMock()
        candidate_id = uuid.uuid4()
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.get.return_value = _candidate(candidate_id)
        session.flush = MagicMock()

        svc = TrackerService(session)
        position = svc.open_position(str(candidate_id))

        assert position is not None
        assert position.status == "OPEN"
        assert position.candidate_id == candidate_id
        assert session.get.return_value.court_decision == CourtDecision.PAPER_TRADE.value
        session.add.assert_called_once_with(position)
        session.flush.assert_called_once()

    def test_open_position_returns_none_if_already_open(self):
        session = MagicMock()
        candidate_id = uuid.uuid4()
        existing = PaperPosition(
            id=uuid.uuid4(),
            candidate_id=candidate_id,
            status="OPEN",
            legs_json=[],
        )
        session.query.return_value.filter_by.return_value.first.return_value = existing

        svc = TrackerService(session)
        result = svc.open_position(str(candidate_id))
        assert result is None
        session.add.assert_not_called()

    def test_open_position_returns_none_when_candidate_not_approved(self):
        session = MagicMock()
        candidate_id = uuid.uuid4()
        session.query.return_value.filter_by.return_value.first.return_value = None
        candidate = _candidate(candidate_id)
        candidate.court_decision = CourtDecision.WATCHLIST.value
        session.get.return_value = candidate

        svc = TrackerService(session)
        result = svc.open_position(str(candidate_id))

        assert result is None
        session.add.assert_not_called()

    def test_open_position_returns_none_when_global_pause_active(self):
        session = MagicMock()
        candidate_id = uuid.uuid4()
        original_pause = settings.runtime_global_pause
        try:
            settings.runtime_global_pause = True
            svc = TrackerService(session)
            result = svc.open_position(str(candidate_id))
        finally:
            settings.runtime_global_pause = original_pause

        assert result is None
        session.query.assert_not_called()
        session.get.assert_not_called()

    def test_open_position_returns_none_when_degraded_read_only_active(self):
        session = MagicMock()
        candidate_id = uuid.uuid4()
        original_read_only = settings.runtime_degraded_read_only
        try:
            settings.runtime_degraded_read_only = True
            svc = TrackerService(session)
            result = svc.open_position(str(candidate_id))
        finally:
            settings.runtime_degraded_read_only = original_read_only

        assert result is None
        session.query.assert_not_called()
        session.get.assert_not_called()

    def test_close_position_updates_record(self):
        session = MagicMock()
        position_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        position = PaperPosition(
            id=position_id,
            candidate_id=candidate_id,
            status="OPEN",
            legs_json=[],
        )
        candidate = _candidate(candidate_id)
        session.get.side_effect = [position, candidate]
        session.flush = MagicMock()

        svc = TrackerService(session)
        result = svc.close_position(str(position_id), actual_pnl=0.05)

        assert result is True
        assert position.status == "CLOSED"
        assert position.actual_pnl == 0.05
        assert position.closed_at is not None
        assert session.get.call_count >= 1

    def test_close_position_returns_false_when_not_found(self):
        session = MagicMock()
        session.get.return_value = None
        svc = TrackerService(session)
        result = svc.close_position(str(uuid.uuid4()), actual_pnl=0.0)
        assert result is False

    def test_close_position_returns_false_when_already_closed(self):
        session = MagicMock()
        position = PaperPosition(
            id=uuid.uuid4(),
            candidate_id=uuid.uuid4(),
            status="CLOSED",
            legs_json=[],
        )
        session.get.return_value = position
        svc = TrackerService(session)
        result = svc.close_position(str(position.id), actual_pnl=0.0)
        assert result is False

    def test_get_open_positions_queries_correctly(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = []
        svc = TrackerService(session)
        svc.get_open_positions()
        session.query.return_value.filter_by.assert_called_with(status="OPEN")
