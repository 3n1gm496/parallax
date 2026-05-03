from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, not_
from sqlalchemy.orm import Session

from parallax.candidates.evidence import load_relation_evidence
from parallax.candidates.repository import CandidateRepository
from parallax.db.models import (
    AuditEvent,
    AutopsyRecord,
    CandidateDecisionSnapshot,
    CounterexampleRecord,
    LogicalRelation,
    LogicalRelationSet,
    OpportunityCandidate,
    PaperPosition,
    RawMarket,
    RelationReview,
    RunProofRecord,
)
from parallax.ops.schemas import (
    OpsActivityMetric,
    AuditOpsMetrics,
    BacktestReplayReport,
    BacktestReplayRow,
    AutopsyOpsMetrics,
    CalibrationOpsMetrics,
    EvaluationOpsMetrics,
    EvaluationReport,
    IdentityReviewQueueEntry,
    IdentityReviewQueueResponse,
    OpsMetricsResponse,
    OpportunityEvaluationSummary,
    PipelineOpsMetrics,
    RelationSetListResponse,
    RelationQualityOpsMetrics,
    RunProof,
    RunProofListResponse,
    RunSummary,
)
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.shared.schemas import IdentityResolutionStatus, LogicalRelationSetSchema, RelationType

_PIPELINE_EVENT_TYPES = (
    "pipeline.compiler.complete",
    "pipeline.identity.complete",
    "pipeline.prover.complete",
    "pipeline.divergence.complete",
)
_LEGACY_EVENT_PREFIX = "oddpool.%"


def get_ops_metrics_payload(session: Session) -> OpsMetricsResponse:
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    non_legacy_audit = not_(AuditEvent.event_type.like(_LEGACY_EVENT_PREFIX))

    market_counts = _group_count_rows(
        session.query(RawMarket.platform, func.count(RawMarket.id)).group_by(RawMarket.platform).all()
    )
    candidate_counts = _group_count_rows(
        session.query(OpportunityCandidate.court_decision, func.count(OpportunityCandidate.id))
        .group_by(OpportunityCandidate.court_decision)
        .all()
    )
    audit_counts = _group_count_rows(
        session.query(AuditEvent.event_type, func.count(AuditEvent.id))
        .filter(non_legacy_audit)
        .group_by(AuditEvent.event_type)
        .all()
    )
    autopsy_counts = _group_count_rows(
        session.query(AutopsyRecord.resolution_type, func.count(AutopsyRecord.id))
        .group_by(AutopsyRecord.resolution_type)
        .all()
    )
    autopsy_rows = session.query(AutopsyRecord).all()
    autopsy_label_counts: dict[str, int] = {}
    for row in autopsy_rows:
        for label in row.labels or []:
            autopsy_label_counts[label] = autopsy_label_counts.get(label, 0) + 1

    open_positions = (
        session.query(func.count(PaperPosition.id)).filter(PaperPosition.status == "OPEN").scalar() or 0
    )
    total_audit_events = session.query(func.count(AuditEvent.id)).filter(non_legacy_audit).scalar() or 0
    audit_events_last_24h = (
        session.query(func.count(AuditEvent.id))
        .filter(non_legacy_audit, AuditEvent.created_at >= last_24h)
        .scalar()
        or 0
    )
    total_autopsy_records = session.query(func.count(AutopsyRecord.id)).scalar() or 0
    identity_errors = (
        session.query(func.count(AutopsyRecord.id))
        .filter(AutopsyRecord.identity_error.is_(True))
        .scalar()
        or 0
    )
    candidate_evaluations_last_24h = (
        session.query(func.count(AuditEvent.id))
        .filter(non_legacy_audit, AuditEvent.event_type == "pipeline.candidate.evaluated", AuditEvent.created_at >= last_24h)
        .scalar()
        or 0
    )
    positions_opened_last_24h = (
        session.query(func.count(AuditEvent.id))
        .filter(non_legacy_audit, AuditEvent.event_type == "pipeline.position.opened", AuditEvent.created_at >= last_24h)
        .scalar()
        or 0
    )
    settlements_last_24h = (
        session.query(func.count(AuditEvent.id))
        .filter(non_legacy_audit, AuditEvent.event_type == "position.settled", AuditEvent.created_at >= last_24h)
        .scalar()
        or 0
    )

    latest_audit_at = session.query(func.max(AuditEvent.created_at)).filter(non_legacy_audit).scalar()
    latest_autopsy_at = session.query(func.max(AutopsyRecord.created_at)).scalar()
    latest_ingest_at = session.query(func.max(RawMarket.updated_at)).scalar()
    latest_candidate_at = session.query(func.max(OpportunityCandidate.detected_at)).scalar()
    latest_pipeline_event_at = (
        session.query(func.max(AuditEvent.created_at))
        .filter(non_legacy_audit, AuditEvent.event_type.in_(_PIPELINE_EVENT_TYPES))
        .scalar()
    )

    activity_metrics = {
        event_type: OpsActivityMetric(
            runs=int(audit_counts.get(event_type, 0)),
            latest_at=latest_event.created_at if latest_event else None,
            latest_payload=latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {},
        )
        for event_type in _PIPELINE_EVENT_TYPES
        for latest_event in [_latest_event_by_type(session, event_type)]
    }
    relation_quality = _build_relation_quality_metrics(session, autopsy_rows)

    return OpsMetricsResponse(
        market_counts_by_platform=market_counts,
        candidate_counts_by_decision=candidate_counts,
        open_positions=int(open_positions),
        latest_audit_at=latest_audit_at,
        latest_ingest_at=latest_ingest_at,
        latest_candidate_at=latest_candidate_at,
        pipeline=PipelineOpsMetrics(
            latest_pipeline_event_at=latest_pipeline_event_at,
            activity_metrics=activity_metrics,
            candidate_evaluations_last_24h=int(candidate_evaluations_last_24h),
            positions_opened_last_24h=int(positions_opened_last_24h),
            settlements_last_24h=int(settlements_last_24h),
            recent_runs=_recent_pipeline_runs(session),
        ),
        audit=AuditOpsMetrics(
            total_events=int(total_audit_events),
            events_last_24h=int(audit_events_last_24h),
            counts_by_event_type=audit_counts,
        ),
        autopsy=AutopsyOpsMetrics(
            total_records=int(total_autopsy_records),
            identity_errors=int(identity_errors),
            counts_by_resolution_type=autopsy_counts,
            counts_by_label=dict(sorted(autopsy_label_counts.items())),
            latest_autopsy_at=latest_autopsy_at,
        ),
        calibration=_build_calibration_metrics(
            autopsy_counts=autopsy_counts,
            autopsy_label_counts=autopsy_label_counts,
            total_autopsy_records=int(total_autopsy_records),
        ),
        evaluation=_build_evaluation_metrics(session),
        relation_quality=relation_quality,
    )


def list_run_proofs_payload(session: Session, *, limit: int = 20) -> RunProofListResponse:
    rows = session.query(RunProofRecord).order_by(RunProofRecord.started_at.desc()).limit(limit).all()
    return RunProofListResponse(runs=[_run_proof_to_schema(row) for row in rows])


def get_run_proof_payload(session: Session, run_id: str) -> RunProof | None:
    row = session.get(RunProofRecord, run_id)
    if row is None:
        return None
    return _run_proof_to_schema(row)


def get_evaluation_report_payload(session: Session) -> EvaluationReport:
    return EvaluationReport(
        generated_at=datetime.now(timezone.utc),
        metrics=_build_evaluation_metrics(session),
    )


def get_backtest_replay_payload(session: Session, *, limit: int = 100) -> BacktestReplayReport:
    snapshots = (
        session.query(CandidateDecisionSnapshot, OpportunityCandidate)
        .join(OpportunityCandidate, OpportunityCandidate.id == CandidateDecisionSnapshot.candidate_id)
        .order_by(CandidateDecisionSnapshot.evaluated_at.desc())
        .limit(limit)
        .all()
    )
    if not snapshots:
        return BacktestReplayReport(
            generated_at=datetime.now(timezone.utc),
            total_snapshots=0,
            snapshots_with_positions=0,
            settled_positions=0,
            profitable_settlements=0,
        )

    candidate_ids = [candidate.id for _, candidate in snapshots]
    positions = (
        session.query(PaperPosition)
        .filter(PaperPosition.candidate_id.in_(candidate_ids))
        .all()
    )
    autopsies = (
        session.query(AutopsyRecord)
        .filter(AutopsyRecord.candidate_id.in_(candidate_ids))
        .all()
    )
    positions_by_candidate = {str(position.candidate_id): position for position in positions}
    autopsies_by_candidate: dict[str, list[AutopsyRecord]] = {}
    for autopsy in autopsies:
        autopsies_by_candidate.setdefault(str(autopsy.candidate_id), []).append(autopsy)

    rows: list[BacktestReplayRow] = []
    stored_edges: list[float] = []
    realized_pnls: list[float] = []
    edge_capture_ratios: list[float] = []
    profitable_settlements = 0
    snapshots_with_positions = 0
    settled_positions = 0
    outcomes_by_type: dict[str, int] = {}

    for snapshot, candidate in snapshots:
        candidate_id = str(candidate.id)
        position = positions_by_candidate.get(candidate_id)
        autopsy_rows = autopsies_by_candidate.get(candidate_id, [])
        simulation = snapshot.simulation_result or {}
        assessment = snapshot.court_assessment or {}
        relation = snapshot.relation_evidence or {}
        stored_edge = _coerce_float(simulation.get("executable_edge"))
        fill_probability = _coerce_float(simulation.get("fill_probability"))
        composite_risk = _coerce_float(assessment.get("composite_risk"))
        actual_pnl = _coerce_float(getattr(position, "actual_pnl", None)) if position is not None else None
        resolution_type = autopsy_rows[-1].resolution_type if autopsy_rows else None
        labels = sorted({label for row in autopsy_rows for label in (row.labels or [])})

        if position is None:
            replay_outcome = "no_position_opened"
        elif position.status == "OPEN":
            replay_outcome = "open_position"
            snapshots_with_positions += 1
        else:
            snapshots_with_positions += 1
            settled_positions += 1
            if any(row.identity_error for row in autopsy_rows) or resolution_type == "IDENTITY_ERROR":
                replay_outcome = "identity_invalidated"
            elif resolution_type == "ORACLE_DIVERGENCE":
                replay_outcome = "oracle_invalidated"
            elif actual_pnl is not None and actual_pnl > 0:
                profitable_settlements += 1
                replay_outcome = "profitable_settlement"
            elif actual_pnl is not None and actual_pnl <= 0:
                replay_outcome = "failed_settlement"
            else:
                replay_outcome = "closed_without_pnl"

        if stored_edge is not None:
            stored_edges.append(stored_edge)
        if actual_pnl is not None:
            realized_pnls.append(actual_pnl)
        edge_capture_ratio = None
        if stored_edge is not None and stored_edge > 0 and actual_pnl is not None:
            edge_capture_ratio = actual_pnl / stored_edge
            edge_capture_ratios.append(edge_capture_ratio)

        outcomes_by_type[replay_outcome] = outcomes_by_type.get(replay_outcome, 0) + 1
        rows.append(
            BacktestReplayRow(
                candidate_id=candidate_id,
                detected_at=candidate.detected_at,
                opportunity_type=str(candidate.opportunity_type),
                court_decision_at_snapshot=str(assessment.get("decision")) if assessment.get("decision") else None,
                relation_type_at_snapshot=RelationType(str(relation["relation_type"])) if relation.get("relation_type") else None,
                tradeable_relation_at_snapshot=bool(relation.get("tradeable_relation")) if relation.get("tradeable_relation") is not None else None,
                identity_status_at_snapshot=str(relation.get("identity_status")) if relation.get("identity_status") else None,
                snapshot_run_id=snapshot.run_id,
                snapshot_evaluated_at=snapshot.evaluated_at,
                stored_executable_edge=stored_edge,
                stored_fill_probability=fill_probability,
                stored_composite_risk=composite_risk,
                position_status=getattr(position, "status", None),
                position_opened_at=getattr(position, "opened_at", None),
                position_closed_at=getattr(position, "closed_at", None),
                actual_pnl=actual_pnl,
                edge_capture_ratio=_safe_round(edge_capture_ratio),
                resolution_type=resolution_type,
                autopsy_labels=labels,
                replay_outcome=replay_outcome,
            )
        )

    return BacktestReplayReport(
        generated_at=datetime.now(timezone.utc),
        total_snapshots=len(snapshots),
        snapshots_with_positions=snapshots_with_positions,
        settled_positions=settled_positions,
        profitable_settlements=profitable_settlements,
        realized_win_rate=_safe_round(profitable_settlements / settled_positions) if settled_positions else None,
        average_stored_edge=_safe_round(sum(stored_edges) / len(stored_edges)) if stored_edges else None,
        average_realized_pnl=_safe_round(sum(realized_pnls) / len(realized_pnls)) if realized_pnls else None,
        average_edge_capture_ratio=_safe_round(sum(edge_capture_ratios) / len(edge_capture_ratios))
        if edge_capture_ratios
        else None,
        false_positive_rate=_safe_round((settled_positions - profitable_settlements) / settled_positions)
        if settled_positions
        else None,
        outcomes_by_type=dict(sorted(outcomes_by_type.items())),
        rows=rows,
    )


def get_identity_review_queue_payload(session: Session, *, limit: int = 100) -> IdentityReviewQueueResponse:
    return _build_identity_review_queue(session, limit=limit)


def list_relation_sets_payload(
    session: Session,
    *,
    limit: int = 100,
    relation_type: RelationType | None = None,
) -> RelationSetListResponse:
    repo = PostgresGraphRepository(session)
    items = [_relation_set_to_schema(item) for item in repo.list_relation_sets(limit=limit, relation_type=relation_type)]
    return RelationSetListResponse(items=items)


def get_relation_set_payload(session: Session, set_key: str) -> LogicalRelationSetSchema | None:
    repo = PostgresGraphRepository(session)
    item = repo.get_relation_set(set_key)
    if item is None:
        return None
    return _relation_set_to_schema(item)


def _group_count_rows(rows: list[tuple[object, int]]) -> dict[str, int]:
    return {str(key): int(value) for key, value in rows if key is not None}


def _relation_set_to_schema(payload: dict[str, object]) -> LogicalRelationSetSchema:
    return LogicalRelationSetSchema(
        relation_set_id=str(payload["id"]),
        set_key=str(payload["set_key"]),
        member_market_ids=list(payload.get("member_market_ids", [])),
        relation_type=RelationType(str(payload["relation_type"])),
        proof_status=str(payload.get("proof_status", "verified")),
        tradeable_relation=bool(payload.get("tradeable_relation", False)),
        confidence=float(payload.get("confidence", 0.0)),
        created_by=str(payload.get("created_by", "")),
        evidence=dict(payload.get("evidence", {})),
        frame_id=payload.get("frame_id"),
    )


def _build_relation_quality_metrics(
    session: Session,
    autopsy_rows: list[AutopsyRecord],
) -> RelationQualityOpsMetrics:
    proposal_counts = _group_count_rows(
        session.query(RelationReview.proposed_relation_type, func.count(RelationReview.id))
        .group_by(RelationReview.proposed_relation_type)
        .all()
    )
    logic_rejected = _group_count_rows(
        session.query(LogicalRelation.relation_type, func.count(LogicalRelation.id))
        .filter(LogicalRelation.proof_status == "rejected")
        .group_by(LogicalRelation.relation_type)
        .all()
    )
    semantic_veto = _group_count_rows(
        session.query(RelationReview.reviewed_relation_type, func.count(RelationReview.id))
        .filter(
            RelationReview.reviewed_by == "semantic_relation_analyzer",
            RelationReview.tradeable_relation.is_(False),
        )
        .group_by(RelationReview.reviewed_relation_type)
        .all()
    )
    verified_tradeable = session.query(func.count(LogicalRelation.id)).filter(
        LogicalRelation.tradeable_relation.is_(True),
        LogicalRelation.proof_status == "verified",
    ).scalar() or 0
    verified_nontradeable = session.query(func.count(LogicalRelation.id)).filter(
        LogicalRelation.tradeable_relation.is_(False),
    ).scalar() or 0
    verified_counts = _group_count_rows(
        session.query(LogicalRelation.relation_type, func.count(LogicalRelation.id))
        .filter(LogicalRelation.proof_status == "verified")
        .group_by(LogicalRelation.relation_type)
        .all()
    )
    verified_set_counts = _group_count_rows(
        session.query(LogicalRelationSet.relation_type, func.count(LogicalRelationSet.id))
        .filter(LogicalRelationSet.proof_status == "verified")
        .group_by(LogicalRelationSet.relation_type)
        .all()
    )
    counterexample_counts = _group_count_rows(
        session.query(CounterexampleRecord.status, func.count(CounterexampleRecord.id))
        .group_by(CounterexampleRecord.status)
        .all()
    )
    counterexample_hits = int(counterexample_counts.get("recorded", 0))
    counterexample_total = sum(counterexample_counts.values())
    false_positive_by_relation: dict[str, int] = {}
    snapshot_by_candidate = {
        str(row.candidate_id): row
        for row in session.query(CandidateDecisionSnapshot)
        .order_by(CandidateDecisionSnapshot.evaluated_at.desc())
        .all()
    }
    for row in autopsy_rows:
        snapshot = snapshot_by_candidate.get(str(row.candidate_id))
        relation_type = "unknown"
        if snapshot is not None and isinstance(snapshot.relation_evidence, dict):
            relation_type = str(snapshot.relation_evidence.get("relation_type", relation_type))
        false_positive_by_relation[relation_type] = false_positive_by_relation.get(relation_type, 0) + 1

    return RelationQualityOpsMetrics(
        proposal_counts_by_type=proposal_counts,
        logic_rejected_counts_by_type=logic_rejected,
        semantic_veto_counts_by_type=semantic_veto,
        false_positive_autopsy_by_relation_type=false_positive_by_relation,
        counterexample_hit_rate=(counterexample_hits / counterexample_total) if counterexample_total else None,
        counterexample_status_counts=counterexample_counts,
        tradeable_vs_nontradeable_ratio=(
            verified_tradeable / verified_nontradeable if verified_nontradeable else float(verified_tradeable or 0)
        ),
        verified_relation_counts_by_type=verified_counts,
        verified_relation_set_counts_by_type=verified_set_counts,
    )


def _latest_event_by_type(session: Session, event_type: str) -> AuditEvent | None:
    return (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == event_type)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )


def _recent_pipeline_runs(session: Session, limit: int = 5) -> list[RunSummary]:
    proof_rows = session.query(RunProofRecord).order_by(RunProofRecord.started_at.desc()).limit(limit).all()
    if proof_rows:
        return [_run_proof_to_summary(row) for row in proof_rows]

    rows = (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == "pipeline.run.completed")
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    result: list[RunSummary] = []
    for row in rows:
        payload = row.payload or {}
        result.append(
            RunSummary(
                run_id=str(payload.get("run_id")) if payload.get("run_id") else row.entity_id,
                run_status=str(payload.get("run_status", "completed")),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                markets_ingested=int(payload.get("markets_ingested", 0)),
                market_counts_by_platform={
                    str(key): int(value) for key, value in (payload.get("market_counts_by_platform") or {}).items()
                },
                contracts_compiled=int(payload.get("contracts_compiled", 0)),
                events_resolved=int(payload.get("events_resolved", 0)),
                relations_detected=int(payload.get("relations_detected", 0)),
                candidates_found=int(payload.get("candidates_found", 0)),
                candidates_watchlisted=int(payload.get("candidates_watchlisted", 0)),
                positions_opened=int(payload.get("positions_opened", 0)),
                positions_settled=int(payload.get("positions_settled", 0)),
                config_fingerprint=str(payload.get("config_fingerprint")) if payload.get("config_fingerprint") else None,
                provider_fingerprints={
                    str(key): str(value) for key, value in (payload.get("provider_fingerprints") or {}).items()
                },
                errors=[str(item) for item in payload.get("errors", [])],
            )
        )
    return result


def _run_proof_to_summary(row: RunProofRecord) -> RunSummary:
    combined_errors = [str(item) for item in (row.fatal_errors or []) + (row.non_fatal_errors or [])]
    return RunSummary(
        run_id=row.run_id,
        run_status=row.run_status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        markets_ingested=row.markets_ingested,
        market_counts_by_platform={str(key): int(value) for key, value in (row.market_counts_by_platform or {}).items()},
        contracts_compiled=row.contracts_compiled,
        events_resolved=row.events_resolved,
        relations_detected=row.relations_detected,
        candidates_found=row.candidates_found,
        candidates_watchlisted=row.candidates_watchlisted,
        positions_opened=row.positions_opened,
        positions_settled=row.positions_settled,
        config_fingerprint=row.config_fingerprint,
        provider_fingerprints={str(key): str(value) for key, value in (row.provider_fingerprints or {}).items()},
        errors=combined_errors,
    )


def _run_proof_to_schema(row: RunProofRecord) -> RunProof:
    return RunProof(
        run_id=row.run_id,
        run_status=row.run_status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        config_fingerprint=row.config_fingerprint,
        provider_fingerprints={str(key): str(value) for key, value in (row.provider_fingerprints or {}).items()},
        readiness_checks=row.readiness_checks or {},
        control_state=row.control_state or {},
        markets_ingested=row.markets_ingested,
        market_counts_by_platform={str(key): int(value) for key, value in (row.market_counts_by_platform or {}).items()},
        contracts_compiled=row.contracts_compiled,
        events_resolved=row.events_resolved,
        relations_detected=row.relations_detected,
        candidates_found=row.candidates_found,
        candidates_watchlisted=row.candidates_watchlisted,
        positions_opened=row.positions_opened,
        positions_settled=row.positions_settled,
        fatal_errors=[str(item) for item in (row.fatal_errors or [])],
        non_fatal_errors=[str(item) for item in (row.non_fatal_errors or [])],
        proof_version=row.proof_version,
    )


def _build_calibration_metrics(
    autopsy_counts: dict[str, int],
    autopsy_label_counts: dict[str, int],
    total_autopsy_records: int,
) -> CalibrationOpsMetrics:
    total_labeled_autopsies = sum(autopsy_label_counts.values())
    denominator = total_autopsy_records if total_autopsy_records else 1
    label_rate_by_type = {
        label: round(count / denominator, 4) for label, count in sorted(autopsy_label_counts.items())
    }

    feedback_pressure = {
        "semantic_risk": round(
            (autopsy_label_counts.get("false_equivalence", 0) + autopsy_label_counts.get("ambiguity_miss", 0))
            / denominator,
            4,
        ),
        "oracle_risk": round(autopsy_label_counts.get("oracle_mismatch", 0) / denominator, 4),
        "deadline_risk": round(autopsy_label_counts.get("deadline_mismatch", 0) / denominator, 4),
        "execution_risk": round(autopsy_label_counts.get("execution_miss", 0) / denominator, 4),
        "liquidity_risk": round(autopsy_label_counts.get("stale_quote_miss", 0) / denominator, 4),
        "cancellation_risk": round(autopsy_counts.get("CANCELLED", 0) / denominator, 4),
        "source_trust_risk": round(autopsy_label_counts.get("oracle_mismatch", 0) / denominator, 4),
    }

    recommended_adjustments: dict[str, str] = {}
    for component, pressure in feedback_pressure.items():
        if pressure >= 0.25:
            recommended_adjustments[component] = "tighten thresholds and review recent failures"
        elif pressure >= 0.1:
            recommended_adjustments[component] = "watchlist calibration drift"

    return CalibrationOpsMetrics(
        total_labeled_autopsies=total_labeled_autopsies,
        label_rate_by_type=label_rate_by_type,
        feedback_pressure_by_component=feedback_pressure,
        recommended_threshold_adjustments=recommended_adjustments,
    )


def _safe_round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _coerce_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _build_evaluation_metrics(session: Session) -> EvaluationOpsMetrics:
    settled_rows = (
        session.query(PaperPosition, OpportunityCandidate)
        .join(OpportunityCandidate, OpportunityCandidate.id == PaperPosition.candidate_id)
        .filter(PaperPosition.status == "CLOSED")
        .all()
    )
    if not settled_rows:
        return EvaluationOpsMetrics(
            settled_positions=0,
            profitable_settlements=0,
            unprofitable_settlements=0,
            realized_win_rate=None,
            average_expected_edge=None,
            average_realized_pnl=None,
            average_edge_capture_ratio=None,
            false_positive_rate=None,
        )

    autopsy_by_candidate: dict[str, list[AutopsyRecord]] = {}
    autopsy_rows = (
        session.query(AutopsyRecord)
        .filter(AutopsyRecord.candidate_id.in_([candidate.id for _, candidate in settled_rows]))
        .all()
    )
    for row in autopsy_rows:
        autopsy_by_candidate.setdefault(str(row.candidate_id), []).append(row)

    expected_edges: list[float] = []
    realized_pnls: list[float] = []
    capture_ratios: list[float] = []
    profitable = 0
    resolution_mix: dict[str, int] = {}
    failure_labels: dict[str, int] = {}
    opportunity_buckets: dict[str, dict[str, object]] = {}

    for position, candidate in settled_rows:
        actual_pnl = float(position.actual_pnl or 0.0)
        expected_edge = float(candidate.worst_case_payoff)
        opportunity_type = str(candidate.opportunity_type)
        labels_for_candidate: dict[str, int] = {}
        autopsy_for_candidate = autopsy_by_candidate.get(str(candidate.id), [])

        expected_edges.append(expected_edge)
        realized_pnls.append(actual_pnl)
        if expected_edge > 0:
            capture_ratios.append(actual_pnl / expected_edge)
        if actual_pnl > 0:
            profitable += 1

        for autopsy in autopsy_for_candidate:
            resolution_mix[autopsy.resolution_type] = resolution_mix.get(autopsy.resolution_type, 0) + 1
            for label in autopsy.labels or []:
                failure_labels[label] = failure_labels.get(label, 0) + 1
                labels_for_candidate[label] = labels_for_candidate.get(label, 0) + 1

        bucket = opportunity_buckets.setdefault(
            opportunity_type,
            {
                "settled_positions": 0,
                "profitable_settlements": 0,
                "expected_edges": [],
                "realized_pnls": [],
                "capture_ratios": [],
                "failure_labels": {},
            },
        )
        bucket["settled_positions"] = int(bucket["settled_positions"]) + 1
        if actual_pnl > 0:
            bucket["profitable_settlements"] = int(bucket["profitable_settlements"]) + 1
        bucket["expected_edges"].append(expected_edge)
        bucket["realized_pnls"].append(actual_pnl)
        if expected_edge > 0:
            bucket["capture_ratios"].append(actual_pnl / expected_edge)
        for label, count in labels_for_candidate.items():
            bucket["failure_labels"][label] = bucket["failure_labels"].get(label, 0) + count

    settled_positions = len(settled_rows)
    unprofitable = settled_positions - profitable
    opportunity_type_breakdown = [
        OpportunityEvaluationSummary(
            opportunity_type=opportunity_type,
            settled_positions=int(bucket["settled_positions"]),
            profitable_settlements=int(bucket["profitable_settlements"]),
            realized_win_rate=_safe_round(
                int(bucket["profitable_settlements"]) / max(int(bucket["settled_positions"]), 1)
            )
            or 0.0,
            average_expected_edge=_safe_round(sum(bucket["expected_edges"]) / len(bucket["expected_edges"]))
            if bucket["expected_edges"]
            else None,
            average_realized_pnl=_safe_round(sum(bucket["realized_pnls"]) / len(bucket["realized_pnls"]))
            if bucket["realized_pnls"]
            else None,
            average_edge_capture_ratio=_safe_round(sum(bucket["capture_ratios"]) / len(bucket["capture_ratios"]))
            if bucket["capture_ratios"]
            else None,
            failure_labels=dict(sorted(bucket["failure_labels"].items())),
        )
        for opportunity_type, bucket in sorted(
            opportunity_buckets.items(),
            key=lambda item: int(item[1]["settled_positions"]),
            reverse=True,
        )
    ]

    return EvaluationOpsMetrics(
        settled_positions=settled_positions,
        profitable_settlements=profitable,
        unprofitable_settlements=unprofitable,
        realized_win_rate=_safe_round(profitable / settled_positions),
        average_expected_edge=_safe_round(sum(expected_edges) / len(expected_edges)) if expected_edges else None,
        average_realized_pnl=_safe_round(sum(realized_pnls) / len(realized_pnls)) if realized_pnls else None,
        average_edge_capture_ratio=_safe_round(sum(capture_ratios) / len(capture_ratios))
        if capture_ratios
        else None,
        false_positive_rate=_safe_round(unprofitable / settled_positions),
        resolution_mix=dict(sorted(resolution_mix.items())),
        failure_labels=dict(sorted(failure_labels.items())),
        opportunity_type_breakdown=opportunity_type_breakdown,
    )


def _build_identity_review_queue(session: Session, limit: int = 100) -> IdentityReviewQueueResponse:
    repo = CandidateRepository(session)
    false_equivalence_count = 0
    autopsy_total = session.query(func.count(AutopsyRecord.id)).scalar() or 0
    for row in session.query(AutopsyRecord).all():
        false_equivalence_count += sum(1 for label in (row.labels or []) if label == "false_equivalence")
    autopsy_failure_pressure = round(false_equivalence_count / max(int(autopsy_total), 1), 4) if autopsy_total else 0.0

    items: list[IdentityReviewQueueEntry] = []
    for candidate in repo.list_open(limit=limit):
        evidence = load_relation_evidence(session, candidate.market_ids)
        if evidence is None:
            continue
        reasons: list[str] = []
        venue_mismatch_risk = 0.0
        if evidence.identity_status != IdentityResolutionStatus.VERIFIED:
            venue_mismatch_risk += 0.5
            reasons.append(
                evidence.identity_blocking_reason
                or f"identity status is {evidence.identity_status.value}"
            )
        if evidence.identity_provenance is None:
            venue_mismatch_risk += 0.5
            reasons.append("missing shared identity provenance")
        if evidence.oracle_alignment == "mismatch":
            venue_mismatch_risk += 0.25
            reasons.append("oracle mismatch across linked markets")
        if evidence.deadline_alignment == "mismatch":
            venue_mismatch_risk += 0.25
            reasons.append("deadline mismatch across linked markets")

        ambiguity_severity = "low"
        relation_signals = evidence.relation_signals or {}
        if evidence.abstention_reason:
            ambiguity_severity = "high"
            reasons.append(evidence.abstention_reason)
        elif evidence.ambiguity_terms:
            ambiguity_severity = str(relation_signals.get("ambiguity_level", "medium"))
            reasons.append(f"ambiguity terms: {', '.join(evidence.ambiguity_terms)}")
        elif venue_mismatch_risk > 0:
            ambiguity_severity = "medium"

        if ambiguity_severity == "low" and venue_mismatch_risk < 0.5:
            continue

        items.append(
            IdentityReviewQueueEntry(
                candidate_id=str(candidate.id),
                opportunity_type=candidate.opportunity_type,
                expected_edge=float(candidate.worst_case_payoff),
                ambiguity_severity=ambiguity_severity,
                venue_mismatch_risk=round(min(1.0, venue_mismatch_risk), 4),
                autopsy_failure_pressure=autopsy_failure_pressure,
                relation_type=evidence.relation_type,
                reasons=reasons,
            )
        )

    items.sort(
        key=lambda item: (
            0 if item.ambiguity_severity == "high" else 1 if item.ambiguity_severity == "medium" else 2,
            -item.expected_edge,
            -item.venue_mismatch_risk,
            -item.autopsy_failure_pressure,
        )
    )
    return IdentityReviewQueueResponse(generated_at=datetime.now(timezone.utc), items=items[:limit])


def get_proof_bundle_payload(session: Session) -> "ProofBundleReport":
    from parallax.ops.runtime import build_readiness_payload
    from parallax.ops.schemas import ProofBundleReport, ProofCheckItem

    readiness = build_readiness_payload(session)
    runs = list_run_proofs_payload(session, limit=1).runs
    latest_run = runs[0] if runs else None
    metrics = get_ops_metrics_payload(session)

    market_counts = metrics.market_counts_by_platform
    total_markets = sum(market_counts.values())
    total_candidates = sum(metrics.candidate_counts_by_decision.values())
    open_positions = metrics.open_positions

    contracts_compiled = latest_run.contracts_compiled if latest_run else 0
    relations_detected = latest_run.relations_detected if latest_run else 0

    semantic_check = readiness.checks.get("semantic") or {}
    semantic_status = (
        semantic_check.get("status", "unknown")
        if isinstance(semantic_check, dict)
        else getattr(semantic_check, "status", "unknown")
    )

    checklist = [
        ProofCheckItem(
            name="database_ok",
            passed=readiness.database == "ok",
            evidence=f"database={readiness.database}",
        ),
        ProofCheckItem(
            name="polymarket_ingested",
            passed=market_counts.get("polymarket", 0) > 0,
            evidence=f"{market_counts.get('polymarket', 0)} polymarket markets",
        ),
        ProofCheckItem(
            name="kalshi_ingested",
            passed=market_counts.get("kalshi", 0) > 0,
            evidence=f"{market_counts.get('kalshi', 0)} kalshi markets",
        ),
        ProofCheckItem(
            name="compilation_ran",
            passed=contracts_compiled > 0,
            evidence=f"{contracts_compiled} contracts compiled in last run",
        ),
        ProofCheckItem(
            name="relations_detected",
            passed=relations_detected > 0,
            evidence=f"{relations_detected} relations in last run",
        ),
        ProofCheckItem(
            name="run_proof_exists",
            passed=latest_run is not None,
            evidence="run persisted" if latest_run else "no run proof found",
        ),
        ProofCheckItem(
            name="semantic_ok",
            passed=semantic_status == "ok",
            evidence=f"semantic: {semantic_status}",
        ),
    ]

    all_pass = all(item.passed for item in checklist)
    return ProofBundleReport(
        captured_at=datetime.now(timezone.utc),
        readiness_status=readiness.status,
        market_counts_by_platform=market_counts,
        total_markets=total_markets,
        total_candidates=total_candidates,
        open_positions=open_positions,
        contracts_compiled_last_run=contracts_compiled,
        relations_detected_last_run=relations_detected,
        run_proof_exists=latest_run is not None,
        proof_checklist=checklist,
        bundle_status="complete" if all_pass else "partial",
    )
