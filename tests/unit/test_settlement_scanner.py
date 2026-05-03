from __future__ import annotations
import uuid
from unittest.mock import MagicMock, patch

import pytest

from parallax.settlement.scanner import SettlementScannerService


def _make_position(candidate_id: str, legs_json: list[dict]) -> MagicMock:
    pos = MagicMock()
    pos.id = uuid.uuid4()
    pos.candidate_id = uuid.UUID(candidate_id)
    pos.legs_json = legs_json
    pos.status = "OPEN"
    return pos


def _make_candidate(candidate_id: str, payoff_matrix: dict) -> MagicMock:
    cand = MagicMock()
    cand.id = uuid.UUID(candidate_id)
    cand.payoff_matrix = payoff_matrix
    return cand


def _make_market(is_closed: bool, yes_price: float) -> MagicMock:
    m = MagicMock()
    m.is_closed = is_closed
    m.outcome_prices = [yes_price, round(1.0 - yes_price, 6)]
    return m


def _matrix_json(legs: list[dict], total_cost: float = 1.0) -> dict:
    return {
        "legs": legs,
        "total_cost": total_cost,
        "scenarios": [{"name": "win", "description": "win", "payoff": 0.1, "is_breaking": False}],
        "worst_case_payoff": 0.05,
        "best_case_payoff": 0.1,
        "breaking_scenario": None,
        "opportunity_type": "pure_arbitrage",
        "friction_bps": 10,
    }


CAND_ID = "00000000-0000-0000-0000-000000000001"
MKT_A = "polymarket:mkt-a"
MKT_B = "kalshi:mkt-b"


class TestSettlementScannerService:

    def test_no_open_positions_returns_empty(self):
        session = MagicMock()
        svc = SettlementScannerService(session)
        with patch("parallax.settlement.scanner.TrackerService") as MockTracker:
            MockTracker.return_value.get_open_positions.return_value = []
            result = svc.scan_and_settle()
        assert result == []

    def test_market_not_closed_skips_position(self):
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.5, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg])
        cand = _make_candidate(CAND_ID, _matrix_json([leg], total_cost=0.5))
        market = _make_market(is_closed=False, yes_price=0.95)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate, RawMarket
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            result = svc.scan_and_settle()

        assert result == []
        MockTracker.return_value.close_position.assert_not_called()

    def test_ambiguous_price_skips_position(self):
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.5, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg])
        cand = _make_candidate(CAND_ID, _matrix_json([leg], total_cost=0.5))
        market = _make_market(is_closed=True, yes_price=0.5)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            result = svc.scan_and_settle()

        assert result == []
        MockTracker.return_value.close_position.assert_not_called()

    def test_yes_side_yes_resolution_wins(self):
        # side=YES, price=0.4, qty=1.0 → win payoff = (1-0.4)*1.0 = 0.6
        # pnl = 0.6 / 0.4 = 1.5, clamped to 1.0
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg])
        cand = _make_candidate(CAND_ID, _matrix_json([leg], total_cost=0.4))
        market = _make_market(is_closed=True, yes_price=0.95)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        assert actual_pnl_arg == pytest.approx(1.0)

    def test_no_side_no_resolution_wins(self):
        # side=NO, price=0.6, qty=1.0 → win payoff = (1-0.6)*1.0 = 0.4
        # pnl = 0.4 / 0.6 ≈ 0.6667
        leg = {"market_id": MKT_A, "side": "NO", "price": 0.6, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg])
        cand = _make_candidate(CAND_ID, _matrix_json([leg], total_cost=0.6))
        market = _make_market(is_closed=True, yes_price=0.05)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        assert actual_pnl_arg == pytest.approx(0.4 / 0.6, abs=1e-4)

    def test_yes_side_no_resolution_loses(self):
        # side=YES, price=0.4, qty=1.0 → loss payoff = -0.4
        # pnl = -0.4 / 0.4 = -1.0
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg])
        cand = _make_candidate(CAND_ID, _matrix_json([leg], total_cost=0.4))
        market = _make_market(is_closed=True, yes_price=0.05)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        assert actual_pnl_arg == pytest.approx(-1.0)

    def test_multi_leg_pnl_sums_and_normalizes(self):
        # leg A: side=YES, price=0.4, qty=1.0, resolves YES → win payoff = 0.6
        # leg B: side=NO, price=0.55, qty=1.0, resolves NO  → win payoff = 0.45
        # total_cost=0.95, sum=1.05, pnl=1.05/0.95 > 1.0, clamped to 1.0
        leg_a = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        leg_b = {"market_id": MKT_B, "side": "NO", "price": 0.55, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg_a, leg_b])
        cand = _make_candidate(CAND_ID, _matrix_json([leg_a, leg_b], total_cost=0.95))
        market_a = _make_market(is_closed=True, yes_price=0.95)
        market_b = _make_market(is_closed=True, yes_price=0.05)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        def get_side_effect(cls, pk):
            if cls is OpportunityCandidate:
                return cand
            pk_str = str(pk)
            if pk_str == MKT_A:
                return market_a
            if pk_str == MKT_B:
                return market_b
            return None
        session.get.side_effect = get_side_effect

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        assert actual_pnl_arg == pytest.approx(1.0)

    def test_autopsy_recorded_after_close(self):
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        pos = _make_position(CAND_ID, [leg])
        cand = _make_candidate(CAND_ID, _matrix_json([leg], total_cost=0.4))
        market = _make_market(is_closed=True, yes_price=0.95)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService") as MockAutopsy,
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            svc.scan_and_settle()

        MockAutopsy.return_value.record.assert_called_once()
        call_kwargs = MockAutopsy.return_value.record.call_args[1]
        assert call_kwargs["candidate_id"] == CAND_ID
        assert call_kwargs["actual_resolution"] == {MKT_A: "YES"}
        assert call_kwargs["position_id"] == str(pos.id)
