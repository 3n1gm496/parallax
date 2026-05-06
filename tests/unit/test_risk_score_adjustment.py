from __future__ import annotations
import uuid

from parallax.shared.schemas import RiskScore, SimulationResult


def _base_risk(execution_risk=0.05, liquidity_risk=0.08) -> RiskScore:
    return RiskScore.combine(
        oracle=0.1, deadline=0.05, semantic=0.2,
        execution=execution_risk, liquidity=liquidity_risk,
        cancellation=0.05, source_trust=0.08,
    )


def _sim(execution_model="snapshot_based", depth_support=True, partial_fill_risk=0.1) -> SimulationResult:
    return SimulationResult(
        candidate_id="c1",
        simulated_pnl=0.05,
        friction_bps=50,
        fill_probability=0.9,
        is_executable=True,
        note="",
        execution_model=execution_model,
        depth_support=depth_support,
        partial_fill_risk=partial_fill_risk,
    )


def test_adjust_returns_base_unchanged_for_heuristic_model():
    base = _base_risk()
    sim = _sim(execution_model="heuristic")
    result = RiskScore.adjust_from_simulation(base, sim)
    assert result.execution_risk == base.execution_risk
    assert result.liquidity_risk == base.liquidity_risk
    assert result.policy_version == "risk-v2"


def test_adjust_lowers_execution_risk_when_depth_supported():
    base = _base_risk(execution_risk=0.13)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.0))
    assert result.execution_risk == round(max(0.0, 0.13 - 0.08), 4)
    assert result.policy_version == "risk-v2-snapshot"


def test_adjust_raises_execution_risk_when_depth_insufficient():
    base = _base_risk(execution_risk=0.10)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=False, partial_fill_risk=0.0))
    assert result.execution_risk == round(min(1.0, 0.10 + 0.30), 4)
    assert result.policy_version == "risk-v2-snapshot"


def test_adjust_leaves_execution_risk_unchanged_when_depth_unknown():
    base = _base_risk(execution_risk=0.10)
    sim = _sim(depth_support=None)
    result = RiskScore.adjust_from_simulation(base, sim)
    assert result.execution_risk == 0.10


def test_adjust_raises_liquidity_risk_from_partial_fill():
    base = _base_risk(liquidity_risk=0.08)
    # partial_fill_risk=0.7 → 0.7*0.8=0.56 > 0.08
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.7))
    assert result.liquidity_risk == round(0.7 * 0.8, 4)


def test_adjust_keeps_base_liquidity_when_partial_fill_low():
    base = _base_risk(liquidity_risk=0.20)
    # partial_fill_risk=0.1 → 0.1*0.8=0.08 < 0.20 → keep 0.20
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.1))
    assert result.liquidity_risk == 0.20


def test_adjust_recomputes_composite():
    base = _base_risk(execution_risk=0.05, liquidity_risk=0.08)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=False, partial_fill_risk=0.5))
    # composite is mean of all 7 components
    expected_exec = round(min(1.0, 0.05 + 0.30), 4)
    expected_liq = round(max(0.08, 0.5 * 0.8), 4)
    components = [0.1, 0.05, 0.2, expected_exec, expected_liq, 0.05, 0.08]
    expected_composite = round(sum(components) / 7, 4)
    assert result.composite == expected_composite


def test_adjust_clamps_execution_risk_at_zero():
    base = _base_risk(execution_risk=0.03)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.0))
    assert result.execution_risk >= 0.0


def test_adjust_clamps_execution_risk_at_one():
    base = _base_risk(execution_risk=0.90)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=False, partial_fill_risk=0.0))
    assert result.execution_risk <= 1.0


def test_assess_with_snapshots_uses_adjusted_risk_in_composite_gate():
    """When depth_support=False, the composite gate in the assessment should reflect the penalized risk."""
    from unittest.mock import MagicMock, patch
    from parallax.court.service import CourtService
    from parallax.shared.schemas import (
        RiskScore, SimulationResult,
    )

    base_risk = RiskScore.combine(
        oracle=0.05, deadline=0.02, semantic=0.1,
        execution=0.05, liquidity=0.08, cancellation=0.05, source_trust=0.08,
    )
    # With depth_support=False, execution_risk → 0.35 → composite rises

    session = MagicMock()
    svc = CourtService.__new__(CourtService)
    svc._session = session
    svc._repo = MagicMock()
    svc._market_repo = MagicMock()
    svc._graph_repo = MagicMock()
    svc._simulator = MagicMock()

    candidate_id = str(uuid.uuid4())
    candidate = MagicMock()
    candidate.id = candidate_id
    candidate.risk_scores = base_risk.model_dump()
    candidate.worst_case_payoff = 0.05
    candidate.market_ids = ["mkt-a", "mkt-b"]
    candidate.opportunity_type = "pure_arbitrage"
    svc._repo.get.return_value = candidate

    simulation = SimulationResult(
        candidate_id=candidate_id,
        simulated_pnl=0.03,
        friction_bps=50,
        fill_probability=0.9,
        is_executable=True,
        note="",
        execution_model="snapshot_based",
        depth_support=False,
        partial_fill_risk=0.0,
    )
    svc._simulator.simulate_snapshot.return_value = simulation

    svc._market_repo.get.return_value = None
    with patch("parallax.court.service.load_relation_evidence", return_value=None), \
         patch("parallax.court.service.get_relation_signals", return_value={
             "oracle_mismatch": False, "deadline_mismatch": False,
             "source_mismatch": False, "ambiguity_level": "low",
             "ambiguity_terms": [], "shared_ambiguity_terms": [],
         }):
        assessment, sim_out, adjusted_risk = svc.assess_with_snapshots(candidate_id, {})

    assert adjusted_risk is not None
    assert adjusted_risk.execution_risk == round(min(1.0, 0.05 + 0.30), 4)
    assert adjusted_risk.policy_version == "risk-v2-snapshot"
    # composite gate in assessment should reference adjusted composite, not base
    composite_gate = next((g for g in assessment.gates if g.name == "composite_risk"), None)
    if composite_gate is not None:
        assert float(composite_gate.observed) == adjusted_risk.composite


def test_decision_snapshot_persists_adjusted_risk():
    """_persist_evaluation should store adjusted_risk in the decision snapshot when provided."""
    from unittest.mock import MagicMock, patch
    from parallax.court.service import CourtService
    from parallax.shared.schemas import (
        CourtAssessment, CourtDecision, RiskScore, SimulationResult, OpportunityType,
    )

    adjusted_risk = RiskScore.combine(
        oracle=0.05, deadline=0.02, semantic=0.1,
        execution=0.35, liquidity=0.08, cancellation=0.05, source_trust=0.08,
        policy_version="risk-v2-snapshot",
    )
    candidate_id = str(uuid.uuid4())
    simulation = SimulationResult(
        candidate_id=candidate_id,
        simulated_pnl=0.03,
        friction_bps=50,
        fill_probability=0.9,
        is_executable=True,
        note="",
        execution_model="snapshot_based",
    )
    assessment = CourtAssessment(
        decision=CourtDecision.APPROVED,
        simulated_pnl=0.03,
        fill_probability=0.9,
        composite_risk=None,
        reasons=[],
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        relation_type=None,
        risk_flags=[],
        gates=[],
        policy_version="court-v2-snapshot",
    )

    session = MagicMock()
    svc = CourtService.__new__(CourtService)
    svc._session = session
    svc._repo = MagicMock()

    candidate = MagicMock()
    candidate.market_ids = ["mkt-a"]
    svc._repo.get.return_value = candidate

    upserted = {}
    svc._repo.upsert_decision_snapshot.side_effect = lambda cid, **kwargs: upserted.update(kwargs)

    with patch("parallax.court.service.load_relation_evidence", return_value=None):
        svc._persist_evaluation(candidate_id, assessment, simulation, run_id=None, adjusted_risk=adjusted_risk)

    svc._repo.update_decision.assert_called_once()
    svc._repo.upsert_decision_snapshot.assert_called_once()
    call_kwargs = svc._repo.upsert_decision_snapshot.call_args.kwargs
    persisted_risk = call_kwargs.get("risk_score")
    assert persisted_risk is not None
    assert persisted_risk.policy_version == "risk-v2-snapshot"
    assert persisted_risk.execution_risk == adjusted_risk.execution_risk
    assert call_kwargs.get("decision_ledger_entry") is not None
