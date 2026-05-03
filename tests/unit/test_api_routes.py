from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from parallax.api.deps import require_read_access, require_write_access
from parallax.api.routes.audit import list_audit_events
from parallax.api.routes.candidates import get_candidate, get_candidate_decision_snapshot, list_candidates
from parallax.api.routes.markets import get_market, list_markets
from parallax.api.routes.ops import (
    get_backtest_replay,
    get_evaluation_report,
    get_identity_review_queue,
    get_ops_metrics,
    get_policy_report,
    get_relation_set,
    get_run_proof,
    list_relation_sets,
    list_run_proofs,
)
from parallax.api.routes.positions import (
    get_position,
    list_candidate_autopsy,
    list_positions,
    settle_position,
)
from parallax.api.app import health
from parallax.config import settings
from parallax.db.models import AutopsyRecord, OpportunityCandidate, PaperPosition, RawMarket
from parallax.ops.runtime import build_readiness_payload
from parallax.ops.schemas import EvaluationOpsMetrics
from parallax.shared.schemas import (
    AutopsyLabel,
    CourtAssessment,
    CourtDecision,
    DecisionSnapshot,
    DecisionGate,
    Leg,
    OpportunityType,
    PayoffMatrix,
    Scenario,
    SettlementRequest,
    SimulationResult,
)


def _payoff_matrix() -> PayoffMatrix:
    return PayoffMatrix(
        legs=[Leg(market_id="pm:a", side="YES", price=0.45, platform="pm")],
        total_cost=0.45,
        scenarios=[Scenario(name="win", description="win", payoff=0.05, is_breaking=False)],
        worst_case_payoff=0.05,
        best_case_payoff=0.05,
        breaking_scenario=None,
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        friction_bps=10,
    )


def _candidate() -> OpportunityCandidate:
    m = _payoff_matrix()
    return OpportunityCandidate(
        id=uuid.uuid4(),
        market_ids=["pm:a"],
        payoff_matrix=m.model_dump(),
        opportunity_type=OpportunityType.PURE_ARBITRAGE.value,
        worst_case_payoff=0.05,
        friction_bps=10,
        risk_scores={},
        court_decision=CourtDecision.PENDING.value,
        detected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _market() -> RawMarket:
    return RawMarket(
        id="polymarket:abc",
        platform="polymarket",
        market_id="abc",
        title="Will X happen?",
        description="desc",
        resolution_criteria="crit",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
        category=None,
        group_id="g1",
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=None,
        raw_payload={},
    )


def _market_inferred_deadline() -> RawMarket:
    market = _market()
    market.id = "kalshi:def"
    market.platform = "kalshi"
    market.raw_payload = {"deadline_source": "catalog.event_date_end_of_day_utc"}
    return market


def test_health_returns_ok():
    payload = health()
    assert payload["status"] == "ok"
    assert "docs_enabled" in payload
    assert "write_auth_enabled" in payload


def test_build_readiness_payload_maps_provider_and_semantic_state():
    session = MagicMock()
    latest_ts = datetime.now(timezone.utc)

    def _group_query(rows):
        query = MagicMock()
        query.group_by.return_value.all.return_value = rows
        query.filter.return_value.group_by.return_value.all.return_value = rows
        return query

    original_key = settings.anthropic_api_key
    try:
        settings.anthropic_api_key = "test-key"
        session.query.side_effect = [
            _group_query([("polymarket", 12), ("kalshi", 4)]),
            _group_query([("polymarket", latest_ts), ("kalshi", latest_ts)]),
        ]

        payload = build_readiness_payload(session)
    finally:
        settings.anthropic_api_key = original_key

    assert payload.database == "ok"
    assert payload.checks["semantic_analysis"]["status"] == "ok"
    assert payload.checks["providers"]["polymarket"]["market_count"] == 12
    assert payload.checks["providers"]["kalshi"]["provider"] == "native"
    assert payload.checks["providers"]["kalshi"]["market_count"] == 4


def test_build_readiness_payload_marks_missing_semantic_credentials():
    session = MagicMock()

    def _group_query(rows):
        query = MagicMock()
        query.group_by.return_value.all.return_value = rows
        query.filter.return_value.group_by.return_value.all.return_value = rows
        return query

    original_key = settings.anthropic_api_key
    original_semantic_disabled = settings.runtime_semantic_analysis_disabled
    try:
        settings.anthropic_api_key = "placeholder"
        settings.runtime_semantic_analysis_disabled = False
        session.query.side_effect = [
            _group_query([]),
            _group_query([]),
        ]

        payload = build_readiness_payload(session)
    finally:
        settings.anthropic_api_key = original_key
        settings.runtime_semantic_analysis_disabled = original_semantic_disabled

    assert payload.status == "degraded"
    assert payload.checks["semantic_analysis"]["status"] == "misconfigured"
    assert payload.checks["providers"]["kalshi"]["status"] == "missing"


def test_build_readiness_payload_surfaces_runtime_control_degradation():
    session = MagicMock()
    latest_ts = datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc)

    def _group_query(rows):
        query = MagicMock()
        query.group_by.return_value.all.return_value = rows
        query.filter.return_value.group_by.return_value.all.return_value = rows
        return query

    original_key = settings.anthropic_api_key
    original_semantic_disabled = settings.runtime_semantic_analysis_disabled
    original_global_pause = settings.runtime_global_pause
    original_read_only = settings.runtime_degraded_read_only
    try:
        settings.anthropic_api_key = "test-key"
        settings.runtime_semantic_analysis_disabled = True
        settings.runtime_global_pause = True
        settings.runtime_degraded_read_only = False
        session.query.side_effect = [
            _group_query([("polymarket", 10), ("kalshi", 5)]),
            _group_query([("polymarket", latest_ts), ("kalshi", latest_ts)]),
        ]

        payload = build_readiness_payload(session)
    finally:
        settings.anthropic_api_key = original_key
        settings.runtime_semantic_analysis_disabled = original_semantic_disabled
        settings.runtime_global_pause = original_global_pause
        settings.runtime_degraded_read_only = original_read_only

    assert payload.status == "degraded"
    assert payload.checks["semantic_analysis"]["status"] == "disabled"
    assert payload.controls.global_pause is True
    assert payload.controls.degraded_read_only_mode is True
    assert payload.controls.semantic_analysis_disabled is True
    assert "semantic analysis disabled by runtime control" in payload.degraded_reasons
    assert "global pause is active" in payload.degraded_reasons
    assert "runtime is in degraded read-only mode" in payload.degraded_reasons


def test_build_readiness_payload_marks_missing_provider_markets():
    session = MagicMock()

    def _group_query(rows):
        query = MagicMock()
        query.group_by.return_value.all.return_value = rows
        return query

    original_key = settings.anthropic_api_key
    try:
        settings.anthropic_api_key = "test-key"
        session.query.side_effect = [
            _group_query([("polymarket", 10)]),
            _group_query([("polymarket", datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc))]),
        ]

        payload = build_readiness_payload(session)
    finally:
        settings.anthropic_api_key = original_key

    assert payload.status == "degraded"
    assert payload.checks["providers"]["kalshi"]["status"] == "missing"
    assert "kalshi provider has no persisted markets yet" in payload.degraded_reasons


def test_list_candidates_empty():
    session = MagicMock()
    with patch("parallax.api.routes.candidates.CandidateReadService") as MockService:
        MockService.return_value.list_open_summaries.return_value = []
        result = list_candidates(session=session)
    assert result == []


def test_get_candidate_not_found():
    session = MagicMock()
    with patch("parallax.api.routes.candidates.CandidateReadService") as MockService:
        MockService.return_value.get_detail.side_effect = ValueError("missing")
        with pytest.raises(HTTPException) as exc:
            get_candidate(candidate_id=str(uuid.uuid4()), session=session)
    assert exc.value.status_code == 404


def test_get_candidate_includes_simulation_result():
    session = MagicMock()
    candidate = _candidate()
    detail = DecisionSnapshot(
        candidate_id=str(candidate.id),
        run_id=None,
        risk_score=None,
        relation_evidence=None,
        simulation_result=SimulationResult(
            candidate_id=str(candidate.id),
            simulated_pnl=0.05,
            friction_bps=10,
            fill_probability=1.0,
            is_executable=True,
            note="test",
        ),
        court_assessment=None,
        evaluated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    candidate_detail = MagicMock()
    candidate_detail.simulation_result = detail.simulation_result
    candidate_detail.court_assessment = CourtAssessment(
        decision=CourtDecision.APPROVED,
        simulated_pnl=0.05,
        fill_probability=1.0,
        composite_risk=0.1,
        reasons=["test"],
        gates=[DecisionGate(name="simulated_pnl", status="pass", observed="0.05", threshold="> 0")],
    )
    candidate_detail.relation_evidence = None
    candidate_detail.decision_snapshot = None
    with patch("parallax.api.routes.candidates.CandidateReadService") as MockService:
        MockService.return_value.get_detail.return_value = candidate_detail
        result = get_candidate(candidate_id=str(candidate.id), session=session)

    assert result.simulation_result is not None
    assert result.simulation_result.simulated_pnl == 0.05
    assert result.court_assessment is not None
    assert result.relation_evidence is None
    assert result.decision_snapshot is None


def test_get_candidate_decision_snapshot_returns_snapshot():
    session = MagicMock()
    candidate = _candidate()
    snapshot = DecisionSnapshot(
        candidate_id=str(candidate.id),
        run_id="run-1",
        risk_score=None,
        relation_evidence=None,
        simulation_result=None,
        court_assessment=None,
        evaluated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    detail = MagicMock()
    detail.decision_snapshot = snapshot
    with patch("parallax.api.routes.candidates.CandidateReadService") as MockService:
        MockService.return_value.get_detail.return_value = detail
        result = get_candidate_decision_snapshot(candidate_id=str(candidate.id), session=session)
    assert result.run_id == "run-1"


def test_list_audit_empty():
    session = MagicMock()
    with patch("parallax.api.routes.audit.AuditRepository") as MockRepo:
        MockRepo.return_value.list_recent.return_value = []
        result = list_audit_events(session=session)
    assert result == []


def test_get_ops_metrics_maps_counts():
    session = MagicMock()
    latest_ts = datetime.now(timezone.utc)
    candidate_id_a = uuid.uuid4()
    candidate_id_b = uuid.uuid4()

    def _group_query(rows):
        query = MagicMock()
        query.group_by.return_value.all.return_value = rows
        query.filter.return_value.group_by.return_value.all.return_value = rows
        return query

    def _scalar_query(value):
        query = MagicMock()
        query.scalar.return_value = value
        return query

    def _filtered_scalar_query(value):
        query = MagicMock()
        query.filter.return_value.scalar.return_value = value
        return query

    def _latest_event_query(payload):
        query = MagicMock()
        query.filter.return_value.order_by.return_value.first.return_value = MagicMock(
            created_at=latest_ts,
            payload=payload if isinstance(payload, dict) else {},
        )
        return query

    def _all_query(rows):
        query = MagicMock()
        query.all.return_value = rows
        return query

    def _recent_runs_query(rows):
        query = MagicMock()
        query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows
        return query

    def _run_proofs_query(rows):
        query = MagicMock()
        query.order_by.return_value.limit.return_value.all.return_value = rows
        return query

    def _settled_rows_query(rows):
        query = MagicMock()
        query.join.return_value.filter.return_value.all.return_value = rows
        return query

    def _autopsy_candidate_query(rows):
        query = MagicMock()
        query.filter.return_value.all.return_value = rows
        return query

    def _ordered_all_query(rows):
        query = MagicMock()
        query.order_by.return_value.all.return_value = rows
        return query

    session.query.side_effect = [
        _group_query([("kalshi", 12), ("polymarket", 50)]),
        _group_query([("APPROVED", 3), ("WATCHLIST", 2)]),
        _group_query([("pipeline.compiler.complete", 5), ("position.settled", 2)]),
        _group_query([("CORRECT", 4), ("IDENTITY_ERROR", 1)]),
        _all_query(
            [
                MagicMock(labels=["oracle_mismatch", "execution_miss"]),
                MagicMock(labels=["oracle_mismatch"]),
            ]
        ),
        _filtered_scalar_query(4),
        _filtered_scalar_query(18),
        _filtered_scalar_query(7),
        _scalar_query(5),
        _filtered_scalar_query(1),
        _filtered_scalar_query(6),
        _filtered_scalar_query(3),
        _filtered_scalar_query(2),
        _filtered_scalar_query(latest_ts),
        _scalar_query(latest_ts),
        _scalar_query(latest_ts),
        _scalar_query(latest_ts),
        _filtered_scalar_query(latest_ts),
        _latest_event_query({"compiled": 8, "llm_enabled": True}),
        _latest_event_query({"events_resolved": 3}),
        _latest_event_query({"relations": 11}),
        _latest_event_query({"candidates": 2}),
        _group_query([("equivalent", 4), ("mutually_exclusive", 3)]),
        _group_query([("related_but_not_tradeable", 2)]),
        _group_query([("equivalent", 1)]),
            _filtered_scalar_query(5),
            _filtered_scalar_query(10),
            _group_query([("equivalent", 7), ("same_event_family", 2)]),
            _group_query([]),
            _group_query([("recorded", 3), ("none_found", 1)]),
            _ordered_all_query(
                [
                MagicMock(
                    candidate_id=candidate_id_a,
                    relation_evidence={"relation_type": "equivalent"},
                ),
                MagicMock(
                    candidate_id=candidate_id_b,
                    relation_evidence={"relation_type": "mutually_exclusive"},
                ),
            ]
        ),
        _run_proofs_query([]),
        _recent_runs_query(
            [
                MagicMock(
                    entity_id="run-1",
                    payload={
                        "run_id": "run-1",
                        "config_fingerprint": "abc123def456",
                        "markets_ingested": 62,
                        "market_counts_by_platform": {"kalshi": 12, "polymarket": 50},
                        "contracts_compiled": 8,
                        "events_resolved": 3,
                        "relations_detected": 11,
                        "candidates_found": 2,
                        "candidates_watchlisted": 1,
                        "positions_opened": 1,
                        "errors": [],
                    },
                )
            ]
        ),
        _settled_rows_query(
            [
                (
                    MagicMock(status="CLOSED", actual_pnl=0.03, candidate_id=candidate_id_a),
                    MagicMock(
                        id=candidate_id_a,
                        opportunity_type=OpportunityType.PURE_ARBITRAGE.value,
                        worst_case_payoff=0.05,
                    ),
                ),
                (
                    MagicMock(status="CLOSED", actual_pnl=-0.01, candidate_id=candidate_id_b),
                    MagicMock(
                        id=candidate_id_b,
                        opportunity_type=OpportunityType.SEMANTIC_ARBITRAGE.value,
                        worst_case_payoff=0.04,
                    ),
                ),
            ]
        ),
        _autopsy_candidate_query(
            [
                MagicMock(candidate_id=candidate_id_a, resolution_type="CORRECT", labels=["oracle_mismatch"]),
                MagicMock(candidate_id=candidate_id_b, resolution_type="IDENTITY_ERROR", labels=["execution_miss"]),
            ]
        ),
    ]

    result = get_ops_metrics(session=session)

    assert result.market_counts_by_platform == {"kalshi": 12, "polymarket": 50}
    assert result.candidate_counts_by_decision == {"APPROVED": 3, "WATCHLIST": 2}
    assert result.open_positions == 4
    assert result.audit.total_events == 18
    assert result.audit.events_last_24h == 7
    assert result.audit.counts_by_event_type["pipeline.compiler.complete"] == 5
    assert result.autopsy.total_records == 5
    assert result.autopsy.identity_errors == 1
    assert result.autopsy.counts_by_resolution_type == {"CORRECT": 4, "IDENTITY_ERROR": 1}
    assert result.autopsy.counts_by_label == {"oracle_mismatch": 2, "execution_miss": 1}
    assert result.calibration.total_labeled_autopsies == 3
    assert result.calibration.feedback_pressure_by_component["oracle_risk"] == 0.4
    assert result.calibration.feedback_pressure_by_component["execution_risk"] == 0.2
    assert result.calibration.policy_version == "risk-v2"
    assert result.pipeline.candidate_evaluations_last_24h == 6
    assert result.pipeline.positions_opened_last_24h == 3
    assert result.pipeline.settlements_last_24h == 2
    assert result.pipeline.recent_runs[0].run_id == "run-1"
    assert result.pipeline.activity_metrics["pipeline.compiler.complete"].latest_payload == {
        "compiled": 8,
        "llm_enabled": True,
    }
    assert result.pipeline.activity_metrics["pipeline.prover.complete"].runs == 0
    assert result.evaluation.policy_version == "evaluation-v1"
    assert result.evaluation.settled_positions == 2
    assert result.evaluation.profitable_settlements == 1
    assert result.evaluation.unprofitable_settlements == 1
    assert result.evaluation.realized_win_rate == 0.5
    assert result.evaluation.false_positive_rate == 0.5
    assert result.evaluation.average_expected_edge == 0.045
    assert result.evaluation.average_realized_pnl == 0.01
    assert result.evaluation.average_edge_capture_ratio == 0.175
    assert result.evaluation.failure_labels == {"execution_miss": 1, "oracle_mismatch": 1}
    assert result.evaluation.resolution_mix == {"CORRECT": 1, "IDENTITY_ERROR": 1}
    assert result.evaluation.opportunity_type_breakdown[0].opportunity_type == OpportunityType.PURE_ARBITRAGE.value
    assert result.relation_quality.proposal_counts_by_type == {"equivalent": 4, "mutually_exclusive": 3}
    assert result.relation_quality.logic_rejected_counts_by_type == {"related_but_not_tradeable": 2}
    assert result.relation_quality.semantic_veto_counts_by_type == {"equivalent": 1}
    assert result.relation_quality.counterexample_status_counts == {"recorded": 3, "none_found": 1}
    assert result.relation_quality.counterexample_hit_rate == 0.75
    assert result.relation_quality.tradeable_vs_nontradeable_ratio == 0.5
    assert result.relation_quality.verified_relation_set_counts_by_type == {}


def test_list_run_proofs_maps_rows():
    session = MagicMock()
    row = MagicMock(
        run_id="run-1",
        run_status="completed",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
        config_fingerprint="abc",
        provider_fingerprints={"polymarket": "fingerprint"},
        readiness_checks={"providers": {}},
        control_state={"global_pause": False},
        markets_ingested=10,
        market_counts_by_platform={"polymarket": 10},
        contracts_compiled=8,
        events_resolved=2,
        relations_detected=4,
        candidates_found=1,
        candidates_watchlisted=0,
        positions_opened=1,
        positions_settled=0,
        fatal_errors=[],
        non_fatal_errors=[],
        proof_version="run-proof-v1",
    )
    session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [row]
    result = list_run_proofs(session=session)
    assert result.runs[0].run_id == "run-1"
    assert result.runs[0].proof_version == "run-proof-v1"


def test_get_run_proof_not_found():
    session = MagicMock()
    session.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        get_run_proof("missing", session=session)
    assert exc.value.status_code == 404


def test_list_relation_sets_returns_payload():
    session = MagicMock()
    with patch("parallax.api.routes.ops.list_relation_sets_payload") as mock_builder:
        mock_builder.return_value = MagicMock(
            items=[
                MagicMock(
                    set_key="pm:a|pm:b|pm:c",
                    relation_type="exhaustive_partition",
                )
            ]
        )
        result = list_relation_sets(session=session)
    assert result.items[0].set_key == "pm:a|pm:b|pm:c"


def test_get_relation_set_not_found():
    session = MagicMock()
    with patch("parallax.api.routes.ops.get_relation_set_payload") as mock_builder:
        mock_builder.return_value = None
        with pytest.raises(HTTPException) as exc:
            get_relation_set("pm:a|pm:b|pm:c", session=session)
    assert exc.value.status_code == 404


def test_get_relation_set_returns_payload():
    session = MagicMock()
    with patch("parallax.api.routes.ops.get_relation_set_payload") as mock_builder:
        mock_builder.return_value = MagicMock(
            relation_set_id="relset-1",
            set_key="pm:a|pm:b|pm:c",
            member_market_ids=["pm:a", "pm:b", "pm:c"],
            relation_type="exhaustive_partition",
            proof_status="verified",
            tradeable_relation=True,
            confidence=0.81,
            created_by="semantic_relation_analyzer",
            evidence={},
            frame_id="frame-1",
        )
        result = get_relation_set("pm:a|pm:b|pm:c", session=session)
    assert result.set_key == "pm:a|pm:b|pm:c"


def test_get_backtest_replay_returns_payload():
    session = MagicMock()
    with patch("parallax.api.routes.ops.get_backtest_replay_payload") as mock_builder:
        mock_builder.return_value = MagicMock(
            generated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            total_snapshots=1,
            snapshots_with_positions=1,
            settled_positions=1,
            profitable_settlements=1,
            realized_win_rate=1.0,
            average_stored_edge=0.03,
            average_realized_pnl=0.02,
            average_edge_capture_ratio=0.66,
            false_positive_rate=0.0,
            outcomes_by_type={"profitable_settlement": 1},
            rows=[],
            report_version="backtest-replay-v1",
        )
        result = get_backtest_replay(session=session)
    assert result.report_version == "backtest-replay-v1"


def test_get_evaluation_report_wraps_metrics():
    session = MagicMock()
    with patch("parallax.api.routes.ops.get_evaluation_report_payload") as mock_builder:
        mock_builder.return_value = MagicMock(
            report_version="evaluation-report-v1",
            metrics=EvaluationOpsMetrics(
            settled_positions=0,
            profitable_settlements=0,
            unprofitable_settlements=0,
            realized_win_rate=None,
            average_expected_edge=None,
            average_realized_pnl=None,
            average_edge_capture_ratio=None,
            false_positive_rate=None,
            ),
        )
        result = get_evaluation_report(session=session)
    assert result.report_version == "evaluation-report-v1"


def test_get_identity_review_queue_returns_payload():
    session = MagicMock()
    with patch("parallax.api.routes.ops.get_identity_review_queue_payload") as mock_builder:
        mock_builder.return_value = MagicMock(items=[], queue_version="identity-review-v1")
        result = get_identity_review_queue(session=session)
    assert result.queue_version == "identity-review-v1"


def test_get_policy_report_returns_payload():
    session = MagicMock()
    with patch("parallax.api.routes.ops.get_policy_report_payload") as mock_builder:
        mock_builder.return_value = MagicMock(
            policy_version="policy-v1",
            calibration_policy_version="risk-v2",
            recommendations=[],
            report_version="policy-report-v1",
        )
        result = get_policy_report(session=session)
    assert result.report_version == "policy-report-v1"


def test_list_markets_maps_summary():
    session = MagicMock()
    market = _market()
    with patch("parallax.api.routes.markets.MarketRepository") as MockRepo:
        MockRepo.return_value.list_open.return_value = [market]
        result = list_markets(session=session)
    assert len(result) == 1
    assert result[0].id == "polymarket:abc"
    assert result[0].deadline_precision == "exact"


def test_get_market_not_found():
    session = MagicMock()
    with patch("parallax.api.routes.markets.MarketRepository") as MockRepo:
        MockRepo.return_value.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            get_market(market_id="polymarket:missing", session=session)
    assert exc.value.status_code == 404


def test_get_market_maps_inferred_deadline_precision():
    session = MagicMock()
    market = _market_inferred_deadline()
    session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
    with patch("parallax.api.routes.markets.MarketRepository") as MockRepo:
        MockRepo.return_value.get.return_value = market
        result = get_market(market_id="kalshi:def", session=session)
    assert result.deadline_precision == "inferred"
    assert result.deadline_source == "catalog.event_date_end_of_day_utc"


def test_list_positions_empty():
    session = MagicMock()
    with patch("parallax.api.routes.positions.TrackerService") as MockTracker:
        MockTracker.return_value.list_positions.return_value = []
        result = list_positions(session=session)
    assert result == []


def test_get_position_not_found():
    session = MagicMock()
    with patch("parallax.api.routes.positions.TrackerService") as MockTracker:
        MockTracker.return_value.get_position.return_value = None
        with pytest.raises(HTTPException) as exc:
            get_position(position_id=str(uuid.uuid4()), session=session)
    assert exc.value.status_code == 404


def test_list_candidate_autopsy_empty():
    session = MagicMock()
    with patch("parallax.api.routes.positions.AutopsyService") as MockAutopsy:
        MockAutopsy.return_value.list_for_candidate.return_value = []
        result = list_candidate_autopsy(candidate_id=str(uuid.uuid4()), session=session)
    assert result == []


def test_settle_position_returns_autopsy_record():
    session = MagicMock()
    position_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    position = PaperPosition(
        id=position_id,
        candidate_id=candidate_id,
        status="OPEN",
        legs_json=[],
    )
    autopsy_record = AutopsyRecord(
        id=uuid.uuid4(),
        candidate_id=candidate_id,
        position_id=position_id,
        actual_resolution={"pm:a": "YES"},
        resolution_type="CORRECT",
        identity_error=False,
        labels=["execution_miss"],
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    with patch("parallax.api.routes.positions.TrackerService") as MockTracker, \
         patch("parallax.api.routes.positions.AutopsyService") as MockAutopsy, \
         patch("parallax.api.routes.positions.AuditService") as MockAudit:
        MockTracker.return_value.get_position.return_value = position
        MockTracker.return_value.close_position.return_value = True
        MockAutopsy.return_value.record.return_value = autopsy_record

        result = settle_position(
            position_id=str(position_id),
            payload=SettlementRequest(
                actual_pnl=0.05,
                actual_resolution={"pm:a": "YES"},
                resolution_type="CORRECT",
                labels=[AutopsyLabel.EXECUTION_MISS],
            ),
            session=session,
        )

    assert result.position_id == str(position_id)
    assert result.labels == [AutopsyLabel.EXECUTION_MISS]
    MockAudit.return_value.record.assert_called_once()


def test_settlement_request_rejects_empty_resolution():
    with pytest.raises(ValueError):
        SettlementRequest(
            actual_pnl=0.05,
            actual_resolution={},
            resolution_type="CORRECT",
        )


def test_settlement_request_rejects_invalid_resolution_value():
    with pytest.raises(ValueError):
        SettlementRequest(
            actual_pnl=0.05,
            actual_resolution={"pm:a": "MAYBE"},
            resolution_type="CORRECT",
        )


def test_write_access_requires_token_when_configured():
    original_token = settings.api_auth_token
    try:
        settings.api_auth_token = "secret-token"
        with pytest.raises(HTTPException) as exc:
            require_write_access(authorization=None, x_api_token=None)
        assert exc.value.status_code == 401
    finally:
        settings.api_auth_token = original_token


def test_read_access_requires_token_when_enabled():
    original_token = settings.api_auth_token
    original_require_reads = settings.api_require_auth_for_reads
    try:
        settings.api_auth_token = "secret-token"
        settings.api_require_auth_for_reads = True
        with pytest.raises(HTTPException) as exc:
            require_read_access(authorization=None, x_api_token=None)
        assert exc.value.status_code == 401
    finally:
        settings.api_auth_token = original_token
        settings.api_require_auth_for_reads = original_require_reads
