from __future__ import annotations

import uuid
from datetime import datetime, timezone

from parallax.db.models import OpportunityCandidate, RunProofRecord, ShadowCandidateObservation
from parallax.ops.candidate_funnel import CandidateDiagnosticsService


def _obs(
    *,
    run_id: str,
    relation_key: str,
    identity_status: str = "verified",
    proof_status: str = "verified",
    tradeable_relation: bool = True,
    displayed_edge: float | None = 0.02,
    executable_edge: float | None = 0.02,
    blocking_gates: list[str] | None = None,
    minimal_relaxation: list[str] | None = None,
    relaxation_flags: dict[str, bool] | None = None,
    solver_called: bool = True,
    solver_skip_reason: str | None = None,
    solver_none_reason: str | None = None,
    rejected_by_threshold: bool = False,
    rejected_by_identity: bool = False,
    rejected_by_false_arbitrage: bool = False,
    rejected_by_dedup: bool = False,
    false_arbitrage_label: str | None = None,
    persisted_candidate_id: uuid.UUID | None = None,
) -> ShadowCandidateObservation:
    return ShadowCandidateObservation(
        id=uuid.uuid4(),
        run_id=run_id,
        relation_key=relation_key,
        relation_kind="relation",
        relation_type="equivalent",
        market_ids=[f"pm:{relation_key}", f"kalshi:{relation_key}"],
        identity_status=identity_status,
        identity_version="identity-v3-runtime",
        proof_status=proof_status,
        tradeable_relation=tradeable_relation,
        solver_called=solver_called,
        solver_skip_reason=solver_skip_reason,
        solver_none_reason=solver_none_reason,
        displayed_edge=displayed_edge,
        executable_edge=executable_edge,
        worst_case_payoff=displayed_edge,
        valid_state_count=2,
        impossible_state_count=0,
        false_arbitrage_label=false_arbitrage_label,
        min_profit_threshold=0.005,
        rejected_by_threshold=rejected_by_threshold,
        rejected_by_identity=rejected_by_identity,
        rejected_by_false_arbitrage=rejected_by_false_arbitrage,
        rejected_by_dedup=rejected_by_dedup,
        execution_evidence_missing=True,
        blocking_gates=blocking_gates or [],
        relaxation_flags=relaxation_flags or {},
        minimal_relaxation=minimal_relaxation or [],
        dangerous_relaxation=bool(minimal_relaxation),
        persisted_candidate_id=persisted_candidate_id,
        metadata_json={},
        created_at=datetime.now(timezone.utc),
    )


def test_candidate_diagnostics_reports_blockers_and_sensitivity(test_session):
    run_id = "run-diag-1"
    persisted_candidate_id = uuid.uuid4()
    test_session.add(
        RunProofRecord(
            run_id=run_id,
            run_status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            config_fingerprint="cfg",
            provider_fingerprints={},
            readiness_checks={},
            control_state={},
            markets_ingested=5,
            market_counts_by_platform={"polymarket": 3, "kalshi": 2},
            contracts_compiled=5,
            events_resolved=3,
            relations_detected=4,
            candidates_found=1,
            candidates_watchlisted=0,
            positions_opened=0,
            positions_settled=0,
            fatal_errors=[],
            non_fatal_errors=[],
        )
    )
    test_session.add(
        OpportunityCandidate(
            id=persisted_candidate_id,
            market_ids=["pm:persisted", "kalshi:persisted"],
            payoff_matrix={},
            opportunity_type="duplicate_divergence",
            worst_case_payoff=0.02,
            friction_bps=50,
            risk_scores={},
            court_decision="PENDING",
            status="open",
            detected_at=datetime.now(timezone.utc),
        )
    )
    test_session.add_all(
        [
            _obs(
                run_id=run_id,
                relation_key="identity",
                displayed_edge=None,
                executable_edge=None,
                blocking_gates=["identity_gate"],
                minimal_relaxation=["identity_gate_relaxed"],
                relaxation_flags={"identity_gate_relaxed": True},
                solver_called=False,
                solver_skip_reason="identity_not_verified",
                identity_status="ambiguous",
                proof_status="needs_review",
                tradeable_relation=False,
                rejected_by_identity=True,
            ),
            _obs(
                run_id=run_id,
                relation_key="threshold",
                blocking_gates=["min_profit_threshold"],
                minimal_relaxation=["min_profit_threshold_relaxed"],
                relaxation_flags={"min_profit_threshold_relaxed": True},
                displayed_edge=0.003,
                executable_edge=0.003,
                rejected_by_threshold=True,
            ),
            _obs(
                run_id=run_id,
                relation_key="falsearb",
                blocking_gates=["false_arbitrage_gate"],
                displayed_edge=0.02,
                executable_edge=0.02,
                false_arbitrage_label="proof_needs_review",
                rejected_by_false_arbitrage=True,
            ),
            _obs(
                run_id=run_id,
                relation_key="dedup",
                blocking_gates=["dedup_gate"],
                minimal_relaxation=["dedup_disabled"],
                relaxation_flags={"dedup_disabled": True},
                displayed_edge=0.02,
                executable_edge=0.02,
                rejected_by_dedup=True,
            ),
            _obs(
                run_id=run_id,
                relation_key="persisted",
                displayed_edge=0.02,
                executable_edge=0.02,
                persisted_candidate_id=persisted_candidate_id,
            ),
        ]
    )
    test_session.commit()

    service = CandidateDiagnosticsService(test_session)
    funnel = service.build_candidate_funnel_report(run_id)
    assert funnel.run_id == run_id
    assert funnel.persistence.persisted_candidates == 1
    assert funnel.persistence.duplicate_dedup == 1
    assert funnel.persistence.rejected_false_arbitrage == 1
    assert funnel.preview.failed_only_identity_unverified == 1
    assert funnel.preview.failed_only_profit_below_threshold == 1
    assert funnel.solver.solver_not_called == 1
    assert funnel.top_blockers[0].reason in {"identity_gate", "min_profit_threshold", "false_arbitrage_gate", "dedup_gate"}

    shadow = service.build_shadow_candidates_report(run_id)
    assert shadow.total == 5
    assert any(row.minimal_relaxation == ["identity_gate_relaxed"] for row in shadow.rows)

    sensitivity = service.build_sensitivity_report(run_id)
    threshold_counts = {row.label: row.count for row in sensitivity.min_profit_thresholds}
    assert threshold_counts["0 bps"] >= threshold_counts["50 bps"]
    identity_counts = {row.label: row.count for row in sensitivity.identity_gates}
    assert identity_counts["verified or ambiguous"] >= identity_counts["verified only"]


def test_shadow_candidates_endpoint_contract(test_session):
    run_id = "run-diag-2"
    test_session.add(
        RunProofRecord(
            run_id=run_id,
            run_status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            config_fingerprint="cfg",
            provider_fingerprints={},
            readiness_checks={},
            control_state={},
            markets_ingested=0,
            market_counts_by_platform={},
            contracts_compiled=0,
            events_resolved=0,
            relations_detected=0,
            candidates_found=0,
            candidates_watchlisted=0,
            positions_opened=0,
            positions_settled=0,
            fatal_errors=[],
            non_fatal_errors=[],
        )
    )
    test_session.add(
        _obs(
            run_id=run_id,
            relation_key="shadow-only",
            blocking_gates=["identity_gate"],
            minimal_relaxation=["identity_gate_relaxed"],
            relaxation_flags={"identity_gate_relaxed": True},
            solver_called=False,
            solver_skip_reason="identity_not_verified",
            identity_status="ambiguous",
            displayed_edge=None,
            executable_edge=None,
            rejected_by_identity=True,
        )
    )
    test_session.commit()

    shadow = CandidateDiagnosticsService(test_session).build_shadow_candidates_report(run_id)
    assert shadow.run_id == run_id
    assert shadow.rows[0].blocking_gates == ["identity_gate"]
    assert shadow.rows[0].minimal_relaxation == ["identity_gate_relaxed"]
