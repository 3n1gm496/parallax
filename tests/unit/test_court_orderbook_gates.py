from __future__ import annotations


from parallax.court.service import CourtService
from parallax.shared.schemas import SimulationResult


def _sim(
    staleness: float | None = 10.0,
    depth_support: bool = True,
    partial_fill_risk: float = 0.1,
    simulated_pnl: float = 0.05,
) -> SimulationResult:
    return SimulationResult(
        candidate_id="cand-1",
        displayed_edge=0.05,
        executable_edge=simulated_pnl,
        simulated_pnl=simulated_pnl,
        friction_bps=50,
        fill_probability=0.90,
        is_executable=True,
        note="test",
        execution_model="snapshot_based",
        quote_staleness_seconds=staleness,
        depth_support=depth_support,
        partial_fill_risk=partial_fill_risk,
    )


def test_orderbook_gates_all_pass():
    gates, reasons, downgrade = CourtService._orderbook_gates(_sim(
        staleness=5.0, depth_support=True, partial_fill_risk=0.1
    ))
    statuses = {g.name: g.status for g in gates}
    assert statuses["quote_staleness"] == "pass"
    assert statuses["depth_support"] == "pass"
    assert statuses["partial_fill_inversion"] == "pass"
    assert downgrade is False


def test_orderbook_gates_stale_quote_triggers_watchlist():
    gates, reasons, downgrade = CourtService._orderbook_gates(_sim(staleness=120.0))
    statuses = {g.name: g.status for g in gates}
    assert statuses["quote_staleness"] == "watchlist"
    assert downgrade is True
    assert any("staleness" in r for r in reasons)


def test_orderbook_gates_insufficient_depth_triggers_watchlist():
    gates, reasons, downgrade = CourtService._orderbook_gates(_sim(depth_support=False))
    statuses = {g.name: g.status for g in gates}
    assert statuses["depth_support"] == "watchlist"
    assert downgrade is True


def test_orderbook_gates_high_partial_fill_risk_triggers_watchlist():
    gates, reasons, downgrade = CourtService._orderbook_gates(_sim(partial_fill_risk=0.8))
    statuses = {g.name: g.status for g in gates}
    assert statuses["partial_fill_inversion"] == "watchlist"
    assert downgrade is True


def test_orderbook_gates_no_staleness_skips_gate():
    gates, _, _ = CourtService._orderbook_gates(_sim(staleness=None))
    names = {g.name for g in gates}
    assert "quote_staleness" not in names


def test_orderbook_gates_no_depth_support_info_skips_gate():
    sim = _sim()
    sim.depth_support = None
    gates, _, _ = CourtService._orderbook_gates(sim)
    names = {g.name for g in gates}
    assert "depth_support" not in names
