from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot
from parallax.shared.schemas import SimulationResult


def _make_snapshot(market_id: str, ask_price: float = 0.46, ask_size: float = 200.0) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id=str(uuid.uuid4()),
        platform="polymarket",
        market_id=market_id,
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=ask_price - 0.01, size=200.0)]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=ask_price, size=ask_size)]),
        mid_price=ask_price - 0.005,
    )


def _make_simulator(candidate_id: str, payoff: float = 0.05):
    from parallax.simulator.service import SimulatorService
    from parallax.shared.schemas import PayoffMatrix, Leg, Scenario, OpportunityType

    leg = Leg(market_id="mkt-a", side="YES", price=0.45, quantity=100.0, platform="polymarket")
    matrix = PayoffMatrix(
        legs=[leg],
        total_cost=45.0,
        scenarios=[Scenario(name="YES wins", description="base", payoff=payoff)],
        worst_case_payoff=payoff,
        best_case_payoff=payoff,
        breaking_scenario=None,
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        friction_bps=50,
    )

    candidate = MagicMock()
    candidate.id = candidate_id
    candidate.payoff_matrix = matrix.model_dump(mode="json")
    candidate.risk_scores = None
    candidate.market_ids = ["mkt-a"]
    candidate.opportunity_type = "pure_arbitrage"

    session = MagicMock()
    svc = SimulatorService.__new__(SimulatorService)
    svc._session = session
    svc._repo = MagicMock()
    svc._repo.get.return_value = candidate
    svc._graph_repo = MagicMock()
    svc._graph_repo.get_relations.return_value = []
    return svc


def test_simulate_snapshot_snapshot_based_model():
    svc = _make_simulator("cand-1")
    snap = _make_snapshot("mkt-a", ask_price=0.46, ask_size=200.0)
    result = svc.simulate_snapshot("cand-1", {"mkt-a": snap})

    assert result.execution_model == "snapshot_based"
    assert result.depth_support is True
    assert isinstance(result.snapshot_ids, list)
    assert len(result.snapshot_ids) == 1


def test_simulate_snapshot_degraded_when_missing():
    svc = _make_simulator("cand-1")
    # No snapshot provided → degraded
    result = svc.simulate_snapshot("cand-1", {})

    assert result.execution_model == "degraded"


def test_simulate_snapshot_insufficient_depth_not_supported():
    svc = _make_simulator("cand-1")
    # Ask size = 5, quantity = 100 → insufficient
    snap = _make_snapshot("mkt-a", ask_price=0.46, ask_size=5.0)
    result = svc.simulate_snapshot("cand-1", {"mkt-a": snap})

    assert result.depth_support is False
    assert result.is_executable is False


def test_simulate_snapshot_displayed_vs_executable_edge():
    svc = _make_simulator("cand-1", payoff=0.05)
    # VWAP > stored price → slippage drag
    snap = _make_snapshot("mkt-a", ask_price=0.50, ask_size=200.0)
    result = svc.simulate_snapshot("cand-1", {"mkt-a": snap})

    assert result.displayed_edge == pytest.approx(0.05)
    # executable_edge = 0.05 - slippage; slippage = (0.50-0.45)*100 = 5.0
    # simulated_pnl = 0.05 - 5.0 < 0 → not executable
    assert result.executable_edge < result.displayed_edge


def test_simulate_snapshot_stale_snapshot_adds_flag():
    svc = _make_simulator("cand-1")
    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    snap = OrderbookSnapshot(
        id=str(uuid.uuid4()),
        platform="polymarket",
        market_id="mkt-a",
        outcome="YES",
        captured_at=old_ts,
        asks=OrderbookSide(levels=[OrderbookLevel(price=0.46, size=200.0)]),
    )
    result = svc.simulate_snapshot("cand-1", {"mkt-a": snap})

    assert "stale_quote" in result.risk_flags
    assert result.is_executable is False
