from __future__ import annotations

from unittest.mock import MagicMock, patch


from parallax.execution.replay_stats import ReplayStats
from parallax.shared.schemas import (
    Leg,
    PayoffMatrix,
    RiskScore,
    Scenario,
    SimulationResult,
)
from parallax.simulator.service import SimulatorService


def _make_payoff_matrix() -> PayoffMatrix:
    leg = Leg(
        market_id="mkt-a",
        side="YES",
        price=0.45,
        quantity=100,
        cost=45.0,
        outcome="YES",
        platform="polymarket",
    )
    return PayoffMatrix(
        legs=[leg],
        total_cost=45.0,
        scenarios=[Scenario(name="YES wins", description="base", payoff=0.10, is_breaking=False)],
        worst_case_payoff=0.10,
        best_case_payoff=0.10,
        breaking_scenario=None,
        opportunity_type="pure_arbitrage",
        friction_bps=50,
    )


def _make_candidate(opportunity_type: str = "pure_arbitrage") -> MagicMock:
    candidate = MagicMock()
    candidate.id = "cand-1"
    candidate.market_ids = ["mkt-a"]
    candidate.opportunity_type = opportunity_type
    candidate.worst_case_payoff = 0.10
    candidate.payoff_matrix = _make_payoff_matrix().model_dump()
    candidate.risk_scores = None
    return candidate


def _make_simulator(candidate: MagicMock) -> SimulatorService:
    session = MagicMock()
    svc = SimulatorService.__new__(SimulatorService)
    svc._session = session
    svc._repo = MagicMock()
    svc._repo.get.return_value = candidate
    svc._graph_repo = MagicMock()
    svc._graph_repo.get_relations.return_value = []
    return svc


def test_simulate_replay_returns_heuristic_when_no_history():
    candidate = _make_candidate()
    svc = _make_simulator(candidate)

    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls:
        mock_cls.return_value.get_stats.return_value = None
        result = svc.simulate_replay("cand-1")

    assert result.execution_model == "heuristic"
    assert result.candidate_id == "cand-1"


def test_simulate_replay_sets_execution_model_when_history_available():
    candidate = _make_candidate()
    svc = _make_simulator(candidate)

    stats = ReplayStats(
        opportunity_type="pure_arbitrage",
        n_settled=5,
        win_rate=0.8,
        mean_edge_capture=0.75,
    )

    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls:
        mock_cls.return_value.get_stats.return_value = stats
        result = svc.simulate_replay("cand-1")

    assert result.execution_model == "replay_based"
    assert result.model_version == "replay-v1"


def test_simulate_replay_adjusts_fill_probability():
    candidate = _make_candidate()
    svc = _make_simulator(candidate)

    stats = ReplayStats(
        opportunity_type="pure_arbitrage",
        n_settled=5,
        win_rate=0.6,
        mean_edge_capture=1.0,
    )

    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls:
        mock_cls.return_value.get_stats.return_value = stats
        result = svc.simulate_replay("cand-1")

    assert result.fill_probability == round(min(1.0, max(0.2, 0.6)), 4)


def test_simulate_replay_adjusts_simulated_pnl():
    candidate = _make_candidate()
    svc = _make_simulator(candidate)

    stats = ReplayStats(
        opportunity_type="pure_arbitrage",
        n_settled=5,
        win_rate=0.8,
        mean_edge_capture=0.5,
    )

    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls:
        mock_cls.return_value.get_stats.return_value = stats
        result = svc.simulate_replay("cand-1")

    # compute heuristic independently
    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls2:
        mock_cls2.return_value.get_stats.return_value = None
        heuristic = svc.simulate_replay("cand-1")

    expected_pnl = round(heuristic.simulated_pnl * 0.5, 6)
    assert result.simulated_pnl == expected_pnl


def test_simulate_replay_caps_edge_capture_at_1_5():
    candidate = _make_candidate()
    svc = _make_simulator(candidate)

    stats = ReplayStats(
        opportunity_type="pure_arbitrage",
        n_settled=5,
        win_rate=0.9,
        mean_edge_capture=3.0,
    )

    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls:
        mock_cls.return_value.get_stats.return_value = stats
        result = svc.simulate_replay("cand-1")

    heuristic = svc.simulate("cand-1")
    expected_pnl = round(heuristic.simulated_pnl * 1.5, 6)
    assert result.simulated_pnl == expected_pnl


def test_simulate_replay_clamps_fill_probability_floor():
    candidate = _make_candidate()
    svc = _make_simulator(candidate)

    stats = ReplayStats(
        opportunity_type="pure_arbitrage",
        n_settled=3,
        win_rate=0.0,
        mean_edge_capture=-0.5,
    )

    with patch("parallax.simulator.service.ReplayStatisticsService") as mock_cls:
        mock_cls.return_value.get_stats.return_value = stats
        result = svc.simulate_replay("cand-1")

    assert result.fill_probability >= 0.2


def test_court_evaluate_with_replay_persists_replay_model():
    from parallax.court.service import CourtService

    base_risk = RiskScore.combine(
        oracle=0.05, deadline=0.02, semantic=0.1,
        execution=0.05, liquidity=0.08, cancellation=0.05, source_trust=0.08,
    )
    candidate = MagicMock()
    candidate.id = "cand-1"
    candidate.risk_scores = base_risk.model_dump()
    candidate.worst_case_payoff = 0.05
    candidate.market_ids = ["mkt-a", "mkt-b"]
    candidate.opportunity_type = "pure_arbitrage"

    session = MagicMock()
    svc = CourtService.__new__(CourtService)
    svc._session = session
    svc._repo = MagicMock()
    svc._repo.get.return_value = candidate
    svc._repo.get_decision_snapshot.return_value = None
    svc._market_repo = MagicMock()
    svc._market_repo.get.return_value = None
    svc._graph_repo = MagicMock()
    svc._simulator = MagicMock()

    replay_simulation = SimulationResult(
        candidate_id="cand-1",
        simulated_pnl=0.035,
        friction_bps=50,
        fill_probability=0.8,
        is_executable=True,
        note="replay test",
        execution_model="replay_based",
        model_version="replay-v1",
    )
    svc._simulator.simulate_replay.return_value = replay_simulation

    with patch("parallax.court.service.load_relation_evidence", return_value=None), \
         patch("parallax.court.service.get_relation_signals", return_value={
             "oracle_mismatch": False, "deadline_mismatch": False,
             "source_mismatch": False, "ambiguity_level": "low",
             "ambiguity_terms": [], "shared_ambiguity_terms": [],
         }):
        svc.evaluate_with_replay("cand-1", run_id=None)

    svc._simulator.simulate_replay.assert_called_once_with("cand-1")
    svc._repo.update_decision.assert_called_once()
    persisted_sim = svc._repo.upsert_decision_snapshot.call_args.kwargs.get("simulation_result")
    assert persisted_sim is not None
    assert persisted_sim.execution_model == "replay_based"
