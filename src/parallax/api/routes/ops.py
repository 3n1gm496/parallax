from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from parallax.api.deps import get_read_session, get_write_session, require_read_access, require_write_access
from parallax.calibration.service import CalibrationService
from parallax.certificates.service import CertificateService
from parallax.identity.cluster_repository import IdentityClusterRepository
from parallax.identity.v3_service import IdentityV3Service
from parallax.ops.candidate_funnel import CandidateDiagnosticsService
from parallax.ops.execution_report import ExecutionReportService
from parallax.ops.schemas import (
    BacktestReplayReport,
    CandidateFunnelReport,
    CalibrationStatusResponse,
    CertificateListResponse,
    EvaluationReport,
    ExecutionReport,
    IdentityClusterDetailResponse,
    IdentityClusterQueueResponse,
    IdentityMetricsReport,
    IdentityReviewQueueResponse,
    MergeClustersRequest,
    OpsMetricsResponse,
    PolicyReport,
    ProofBundleReport,
    RelationSetListResponse,
    ScorecardListResponse,
    SensitivityReport,
    ShadowCandidateListResponse,
    SplitClusterRequest,
    StrategyKillListResponse,
    RunProof,
    RunProofListResponse,
)
from parallax.identity.metrics_service import MetricsService
from parallax.identity.split_merge import SplitMergeService
from parallax.policy.service import get_policy_report_payload
from parallax.ops.service import (
    get_backtest_replay_payload,
    get_evaluation_report_payload,
    get_identity_cluster_queue,
    get_identity_metrics_report,
    get_identity_review_queue_payload,
    get_ops_metrics_payload,
    get_proof_bundle_payload,
    get_relation_set_payload,
    get_run_proof_payload,
    list_relation_sets_payload,
    list_run_proofs_payload,
)
from parallax.shared.schemas import LogicalRelationSetSchema, RelationType
import uuid as _uuid

router = APIRouter(tags=["ops"])


@router.get("/ops/metrics", response_model=OpsMetricsResponse)
def get_ops_metrics(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> OpsMetricsResponse:
    return get_ops_metrics_payload(session)


@router.get("/ops/runs", response_model=RunProofListResponse)
def list_run_proofs(
    limit: int = Query(default=20, ge=1, le=100),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> RunProofListResponse:
    return list_run_proofs_payload(session, limit=limit)


@router.get("/ops/runs/{run_id}", response_model=RunProof)
def get_run_proof(
    run_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> RunProof:
    payload = get_run_proof_payload(session, run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Run proof not found")
    return payload


@router.get("/ops/evaluation", response_model=EvaluationReport)
def get_evaluation_report(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> EvaluationReport:
    return get_evaluation_report_payload(session)


@router.get("/ops/backtest", response_model=BacktestReplayReport)
def get_backtest_replay(
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> BacktestReplayReport:
    return get_backtest_replay_payload(session, limit=limit)


@router.get("/ops/identity-review", response_model=IdentityReviewQueueResponse)
def get_identity_review_queue(
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> IdentityReviewQueueResponse:
    return get_identity_review_queue_payload(session, limit=limit)


@router.get("/ops/identity-clusters", response_model=IdentityClusterQueueResponse)
def get_identity_clusters(
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> IdentityClusterQueueResponse:
    return get_identity_cluster_queue(session, limit=limit)


@router.get("/ops/identity-clusters/{cluster_id}", response_model=IdentityClusterDetailResponse)
def get_identity_cluster_detail(
    cluster_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> IdentityClusterDetailResponse:
    repo = IdentityClusterRepository(session)
    cluster = repo.get_cluster(_uuid.UUID(cluster_id))
    if cluster is None:
        raise HTTPException(status_code=404, detail="Identity cluster not found")
    members = repo.list_members(cluster.id)
    actions = repo.list_review_actions(cluster.id)
    history = [
        row
        for row in repo.list_split_merge_history(limit=100)
        if cluster_id in (row.source_cluster_ids or []) or cluster_id in (row.target_cluster_ids or [])
    ]
    entry = get_identity_cluster_queue(session, limit=1000)
    cluster_entry = next((item for item in entry.clusters if item.cluster_id == cluster_id), None)
    if cluster_entry is None:
        raise HTTPException(status_code=404, detail="Identity cluster not found")
    return IdentityClusterDetailResponse(
        cluster=cluster_entry,
        members=[
            {
                "member_id": str(member.id),
                "raw_market_id": member.raw_market_id,
                "canonical_event_id": str(member.canonical_event_id),
                "member_role": member.member_role,
                "added_at": member.added_at,
                "evidence": member.evidence or {},
            }
            for member in members
        ],
        review_actions=[
            {
                "action_id": str(row.id),
                "action": row.action,
                "reviewer": row.reviewer,
                "reason": row.reason,
                "evidence": row.evidence or {},
                "acted_at": row.acted_at,
            }
            for row in actions
        ],
        split_merge_history=[
            {
                "history_id": str(row.id),
                "action": row.action,
                "source_cluster_ids": row.source_cluster_ids,
                "target_cluster_ids": row.target_cluster_ids,
                "triggered_by": row.triggered_by,
                "reason": row.reason,
                "acted_at": row.acted_at,
            }
            for row in history
        ],
    )


@router.post("/ops/identity-clusters/{cluster_id}/review")
def review_identity_cluster(
    cluster_id: str,
    body: dict[str, object],
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_write_session),
) -> dict[str, str]:
    action = str(body.get("action") or "abstain")
    reviewer = str(body.get("reviewer") or body.get("triggered_by") or "operator")
    reason = str(body.get("reason")) if body.get("reason") is not None else None
    try:
        IdentityV3Service(session).review_cluster(
            cluster_id,
            action=action,
            reviewer=reviewer,
            reason=reason,
            evidence=body if isinstance(body, dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cluster_id": cluster_id, "status": "reviewed"}


@router.post("/ops/identity-clusters/{cluster_id}/split")
def split_cluster(
    cluster_id: str,
    body: SplitClusterRequest,
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_write_session),
) -> dict[str, str]:
    try:
        cluster_a, cluster_b = SplitMergeService(session).split_cluster(
            _uuid.UUID(cluster_id),
            split_a_member_ids=body.split_a_member_ids,
            split_b_member_ids=body.split_b_member_ids,
            reason=body.reason,
            triggered_by=body.triggered_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cluster_a_id": str(cluster_a.id), "cluster_b_id": str(cluster_b.id)}


@router.post("/ops/identity-clusters/merge")
def merge_clusters(
    body: MergeClustersRequest,
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_write_session),
) -> dict[str, str]:
    try:
        merged = SplitMergeService(session).merge_clusters(
            [_uuid.UUID(cluster_id) for cluster_id in body.source_cluster_ids],
            reason=body.reason,
            triggered_by=body.triggered_by,
            identity_type=body.identity_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"merged_cluster_id": str(merged.id)}


@router.get("/ops/identity-metrics", response_model=IdentityMetricsReport)
def get_identity_metrics(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> IdentityMetricsReport:
    return get_identity_metrics_report(session)


@router.post("/ops/identity-metrics/recompute")
def recompute_identity_metrics(
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_write_session),
) -> dict[str, object]:
    metric = MetricsService(session).compute_and_persist()
    return {
        "computed_at": metric.computed_at.isoformat(),
        "cluster_count": metric.cluster_count,
        "benchmark_accuracy": metric.benchmark_accuracy,
    }


@router.get("/ops/policy", response_model=PolicyReport)
def get_policy_report(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> PolicyReport:
    return get_policy_report_payload(session)


@router.get("/ops/calibration", response_model=CalibrationStatusResponse)
def get_calibration_status(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> CalibrationStatusResponse:
    svc = CalibrationService(session)
    latest = svc.latest_run()
    active = svc.active_policy()
    return CalibrationStatusResponse(
        latest_run=CalibrationService.run_to_schema(latest) if latest is not None else None,
        active_policy=CalibrationService.policy_to_schema(active) if active is not None else None,
    )


@router.get("/ops/policy/active", response_model=CalibrationStatusResponse)
def get_active_policy_status(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> CalibrationStatusResponse:
    svc = CalibrationService(session)
    active = svc.active_policy()
    return CalibrationStatusResponse(
        latest_run=None,
        active_policy=CalibrationService.policy_to_schema(active) if active is not None else None,
    )


@router.get("/ops/scorecards", response_model=ScorecardListResponse)
def get_scorecards(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> ScorecardListResponse:
    items = CalibrationService(session).list_scorecards()
    return ScorecardListResponse(
        items=[
            {
                "scorecard_id": str(item.id),
                "calibration_run_id": str(item.calibration_run_id),
                "opportunity_type": item.opportunity_type,
                "scorecard": item.scorecard_json or {},
                "created_at": item.created_at,
            }
            for item in items
        ]
    )


@router.get("/ops/strategy-kill-list", response_model=StrategyKillListResponse)
def get_strategy_kill_list(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> StrategyKillListResponse:
    items = CalibrationService(session).list_strategy_kill_list()
    return StrategyKillListResponse(
        items=[
            {
                "strategy_key": item.strategy_key,
                "warning_level": item.warning_level,
                "reason": item.reason,
                "evidence": item.evidence or {},
                "active": item.active,
                "created_at": item.created_at,
            }
            for item in items
        ]
    )


@router.get("/ops/certificates", response_model=CertificateListResponse)
def list_certificates(
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> CertificateListResponse:
    items = CertificateService(session).list_certificates(limit=limit)
    return CertificateListResponse(items=[CertificateService.to_schema(item) for item in items])


@router.get("/ops/relation-sets", response_model=RelationSetListResponse)
def list_relation_sets(
    limit: int = Query(default=100, ge=1, le=500),
    relation_type: RelationType | None = Query(default=None),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> RelationSetListResponse:
    return list_relation_sets_payload(session, limit=limit, relation_type=relation_type)


@router.get("/ops/relation-sets/{set_key:path}", response_model=LogicalRelationSetSchema)
def get_relation_set(
    set_key: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> LogicalRelationSetSchema:
    payload = get_relation_set_payload(session, set_key)
    if payload is None:
        raise HTTPException(status_code=404, detail="Relation set not found")
    return payload


@router.get("/ops/execution", response_model=ExecutionReport)
def get_execution_report(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> ExecutionReport:
    return ExecutionReportService.build(session)


@router.get("/ops/proof", response_model=ProofBundleReport)
def get_proof_bundle(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> ProofBundleReport:
    return get_proof_bundle_payload(session)


@router.get("/ops/candidate-funnel", response_model=CandidateFunnelReport)
def get_candidate_funnel(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> CandidateFunnelReport:
    try:
        return CandidateDiagnosticsService(session).build_candidate_funnel_report()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ops/candidate-funnel/{run_id}", response_model=CandidateFunnelReport)
def get_candidate_funnel_for_run(
    run_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> CandidateFunnelReport:
    return CandidateDiagnosticsService(session).build_candidate_funnel_report(run_id)


@router.get("/ops/shadow-candidates", response_model=ShadowCandidateListResponse)
def get_shadow_candidates(
    limit: int = Query(default=20, ge=1, le=200),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> ShadowCandidateListResponse:
    try:
        return CandidateDiagnosticsService(session).build_shadow_candidates_report(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ops/sensitivity", response_model=SensitivityReport)
def get_sensitivity_report(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> SensitivityReport:
    try:
        return CandidateDiagnosticsService(session).build_sensitivity_report()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
