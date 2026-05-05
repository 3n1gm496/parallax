from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from parallax.shared.schemas import (
    ActivePolicyVersionReport,
    CalibrationRunReport,
    LogicalRelationSetSchema,
    OpportunityType,
    RelationType,
    TradeProofCertificate,
)


class RunSummary(BaseModel):
    run_id: str | None = None
    run_status: str = "completed"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    markets_ingested: int
    market_counts_by_platform: dict[str, int] = Field(default_factory=dict)
    contracts_compiled: int
    events_resolved: int
    relations_detected: int
    candidates_found: int
    candidates_watchlisted: int
    positions_opened: int = 0
    positions_settled: int = 0
    config_fingerprint: str | None = None
    provider_fingerprints: dict[str, str] = Field(default_factory=dict)
    errors: list[str]


class RunProof(BaseModel):
    run_id: str
    run_status: str = "completed"
    started_at: datetime
    completed_at: datetime | None = None
    config_fingerprint: str
    provider_fingerprints: dict[str, str] = Field(default_factory=dict)
    readiness_checks: dict[str, object] = Field(default_factory=dict)
    control_state: dict[str, object] = Field(default_factory=dict)
    markets_ingested: int = 0
    market_counts_by_platform: dict[str, int] = Field(default_factory=dict)
    contracts_compiled: int = 0
    events_resolved: int = 0
    relations_detected: int = 0
    candidates_found: int = 0
    candidates_watchlisted: int = 0
    positions_opened: int = 0
    positions_settled: int = 0
    fatal_errors: list[str] = Field(default_factory=list)
    non_fatal_errors: list[str] = Field(default_factory=list)
    proof_version: str = "run-proof-v1"


class RunProofListResponse(BaseModel):
    runs: list[RunProof] = Field(default_factory=list)


class RuntimeControlState(BaseModel):
    global_pause: bool
    venue_pauses: dict[str, bool] = Field(default_factory=dict)
    semantic_analysis_disabled: bool
    live_execution_enabled: bool
    degraded_read_only_mode: bool
    operator_approval_required: bool = True
    max_exposure: float
    max_daily_loss: float
    max_candidate_concurrency: int
    control_version: str = "runtime-controls-v1"


class ReadinessCheck(BaseModel):
    status: str
    provider: str | None = None
    enabled: bool | None = None
    configured: bool | None = None
    market_count: int | None = None
    latest_market_at: datetime | None = None
    age_minutes: float | None = None
    freshness_threshold_minutes: int | None = None
    min_relation_confidence: float | None = None
    reason: str | None = None


class ReadinessReport(BaseModel):
    status: str
    database: str
    degraded_reasons: list[str] = Field(default_factory=list)
    controls: RuntimeControlState
    checks: dict[str, object]
    orderbook_enabled: bool = False
    venue_token_count: int = 0


class OpsActivityMetric(BaseModel):
    runs: int
    latest_at: datetime | None
    latest_payload: dict[str, object] = Field(default_factory=dict)


class PipelineOpsMetrics(BaseModel):
    latest_pipeline_event_at: datetime | None
    activity_metrics: dict[str, OpsActivityMetric]
    candidate_evaluations_last_24h: int
    positions_opened_last_24h: int
    settlements_last_24h: int
    recent_runs: list[RunSummary] = Field(default_factory=list)


class AuditOpsMetrics(BaseModel):
    total_events: int
    events_last_24h: int
    counts_by_event_type: dict[str, int]


class AutopsyOpsMetrics(BaseModel):
    total_records: int
    identity_errors: int
    counts_by_resolution_type: dict[str, int]
    counts_by_label: dict[str, int] = Field(default_factory=dict)
    latest_autopsy_at: datetime | None


class CalibrationOpsMetrics(BaseModel):
    total_labeled_autopsies: int
    label_rate_by_type: dict[str, float] = Field(default_factory=dict)
    feedback_pressure_by_component: dict[str, float] = Field(default_factory=dict)
    recommended_threshold_adjustments: dict[str, str] = Field(default_factory=dict)
    policy_version: str = "risk-v2"


class PolicyRecommendation(BaseModel):
    component: str
    priority: Literal["high", "medium", "low"]
    pressure: float
    current_value: float | None = None
    recommended_value: float | None = None
    action: str
    basis: list[str] = Field(default_factory=list)


class PolicyReport(BaseModel):
    generated_at: datetime
    policy_version: str = "policy-v1"
    calibration_policy_version: str = "risk-v2"
    identity_risk_pressure: float = 0.0
    semantic_risk_pressure: float = 0.0
    execution_risk_pressure: float = 0.0
    liquidity_risk_pressure: float = 0.0
    oracle_risk_pressure: float = 0.0
    review_queue_size: int = 0
    recent_identity_invalidations: int = 0
    recent_oracle_invalidations: int = 0
    recommendations: list[PolicyRecommendation] = Field(default_factory=list)
    active_policy: ActivePolicyVersionReport | None = None
    report_version: str = "policy-report-v1"


class OpportunityEvaluationSummary(BaseModel):
    opportunity_type: str
    settled_positions: int
    profitable_settlements: int
    realized_win_rate: float
    average_expected_edge: float | None
    average_realized_pnl: float | None
    average_edge_capture_ratio: float | None
    failure_labels: dict[str, int] = Field(default_factory=dict)


class EvaluationOpsMetrics(BaseModel):
    settled_positions: int
    profitable_settlements: int
    unprofitable_settlements: int
    realized_win_rate: float | None
    average_expected_edge: float | None
    average_realized_pnl: float | None
    average_edge_capture_ratio: float | None
    false_positive_rate: float | None
    resolution_mix: dict[str, int] = Field(default_factory=dict)
    failure_labels: dict[str, int] = Field(default_factory=dict)
    opportunity_type_breakdown: list[OpportunityEvaluationSummary] = Field(default_factory=list)
    policy_version: str = "evaluation-v1"


class EvaluationReport(BaseModel):
    generated_at: datetime
    policy_version: str = "evaluation-v1"
    metrics: EvaluationOpsMetrics
    report_version: str = "evaluation-report-v1"


class RelationQualityOpsMetrics(BaseModel):
    proposal_counts_by_type: dict[str, int] = Field(default_factory=dict)
    logic_rejected_counts_by_type: dict[str, int] = Field(default_factory=dict)
    semantic_veto_counts_by_type: dict[str, int] = Field(default_factory=dict)
    false_positive_autopsy_by_relation_type: dict[str, int] = Field(default_factory=dict)
    counterexample_hit_rate: float | None = None
    counterexample_status_counts: dict[str, int] = Field(default_factory=dict)
    tradeable_vs_nontradeable_ratio: float | None = None
    verified_relation_counts_by_type: dict[str, int] = Field(default_factory=dict)
    verified_relation_set_counts_by_type: dict[str, int] = Field(default_factory=dict)
    policy_version: str = "relation-quality-v1"


class IdentityReviewQueueEntry(BaseModel):
    candidate_id: str
    opportunity_type: OpportunityType
    expected_edge: float
    ambiguity_severity: Literal["low", "medium", "high"]
    venue_mismatch_risk: float
    autopsy_failure_pressure: float
    relation_type: RelationType | None = None
    reasons: list[str] = Field(default_factory=list)
    queue_version: str = "identity-review-v1"


class IdentityReviewQueueResponse(BaseModel):
    generated_at: datetime
    items: list[IdentityReviewQueueEntry] = Field(default_factory=list)
    queue_version: str = "identity-review-v1"


class IdentityClusterEntry(BaseModel):
    cluster_id: str
    cluster_key: str
    identity_type: str
    status: str
    confidence: float
    member_count: int
    primary_market_id: str | None = None
    primary_market_title: str | None = None
    created_at: datetime
    provenance: dict[str, object] = Field(default_factory=dict)
    blocking_reasons: list[str] = Field(default_factory=list)


class IdentityClusterQueueResponse(BaseModel):
    generated_at: datetime
    clusters: list[IdentityClusterEntry] = Field(default_factory=list)
    total: int = 0


class IdentityClusterDetailResponse(BaseModel):
    cluster: IdentityClusterEntry
    members: list[dict[str, object]] = Field(default_factory=list)
    review_actions: list[dict[str, object]] = Field(default_factory=list)
    split_merge_history: list[dict[str, object]] = Field(default_factory=list)


class IdentityMetricsReport(BaseModel):
    computed_at: datetime | None = None
    scorer_version: str
    cluster_count: int = 0
    verified_count: int = 0
    ambiguous_count: int = 0
    benchmark_accuracy: float | None = None
    benchmark_total: int = 0
    benchmark_correct: int = 0
    benchmark_wrong: int = 0
    false_merge_count: int = 0
    false_split_count: int = 0
    unresolved_rate: float = 0.0
    ambiguous_rate: float = 0.0


class SplitClusterRequest(BaseModel):
    split_a_member_ids: list[str]
    split_b_member_ids: list[str]
    reason: str
    triggered_by: str = "operator"


class MergeClustersRequest(BaseModel):
    source_cluster_ids: list[str]
    reason: str
    triggered_by: str = "operator"
    identity_type: str = "same_event"


class RelationSetListResponse(BaseModel):
    items: list[LogicalRelationSetSchema] = Field(default_factory=list)


class BacktestReplayRow(BaseModel):
    candidate_id: str
    detected_at: datetime
    opportunity_type: str
    court_decision_at_snapshot: str | None = None
    relation_type_at_snapshot: RelationType | None = None
    tradeable_relation_at_snapshot: bool | None = None
    identity_status_at_snapshot: str | None = None
    snapshot_run_id: str | None = None
    snapshot_evaluated_at: datetime
    stored_executable_edge: float | None = None
    stored_fill_probability: float | None = None
    stored_composite_risk: float | None = None
    position_status: str | None = None
    position_opened_at: datetime | None = None
    position_closed_at: datetime | None = None
    actual_pnl: float | None = None
    edge_capture_ratio: float | None = None
    resolution_type: str | None = None
    autopsy_labels: list[str] = Field(default_factory=list)
    replay_outcome: str


class BacktestReplayReport(BaseModel):
    generated_at: datetime
    total_snapshots: int
    snapshots_with_positions: int
    settled_positions: int
    profitable_settlements: int
    realized_win_rate: float | None = None
    average_stored_edge: float | None = None
    average_realized_pnl: float | None = None
    average_edge_capture_ratio: float | None = None
    false_positive_rate: float | None = None
    outcomes_by_type: dict[str, int] = Field(default_factory=dict)
    rows: list[BacktestReplayRow] = Field(default_factory=list)
    report_version: str = "backtest-replay-v1"


class OpsMetricsResponse(BaseModel):
    market_counts_by_platform: dict[str, int]
    candidate_counts_by_decision: dict[str, int]
    open_positions: int
    latest_audit_at: datetime | None
    latest_ingest_at: datetime | None
    latest_candidate_at: datetime | None
    pipeline: PipelineOpsMetrics
    audit: AuditOpsMetrics
    autopsy: AutopsyOpsMetrics
    calibration: CalibrationOpsMetrics
    evaluation: EvaluationOpsMetrics
    relation_quality: RelationQualityOpsMetrics


class ExecutionCoverageStats(BaseModel):
    platform: str
    venue_token_count: int
    snapshot_count: int
    latest_snapshot_at: datetime | None = None


class ExecutionReport(BaseModel):
    orderbook_enabled: bool
    coverage: list[ExecutionCoverageStats]
    total_venue_tokens: int
    total_snapshots: int
    execution_model_distribution: dict[str, int]
    execution_path_distribution: dict[str, int] = Field(default_factory=dict)
    avg_quote_staleness_seconds: float | None = None
    depth_support_rate: float | None = None
    report_basis: str = "last_500_evaluations"


class CertificateListResponse(BaseModel):
    items: list[TradeProofCertificate] = Field(default_factory=list)


class ScorecardListResponse(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


class StrategyKillListResponse(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


class CalibrationStatusResponse(BaseModel):
    latest_run: CalibrationRunReport | None = None
    active_policy: ActivePolicyVersionReport | None = None


class ProofCheckItem(BaseModel):
    name: str
    passed: bool
    evidence: str


class ProofBundleReport(BaseModel):
    captured_at: datetime
    readiness_status: str
    market_counts_by_platform: dict[str, int] = Field(default_factory=dict)
    total_markets: int = 0
    total_candidates: int = 0
    open_positions: int = 0
    contracts_compiled_last_run: int = 0
    relations_detected_last_run: int = 0
    run_proof_exists: bool = False
    candidates_with_solver_proof: int = 0
    certificates_issued: int = 0
    certificate_gated_positions: int = 0
    decision_ledger_entries: int = 0
    calibration_status: str = "missing"
    execution_evidence_status: str = "blocked"
    proof_checklist: list[ProofCheckItem] = Field(default_factory=list)
    bundle_status: str = "partial"
    bundle_version: str = "proof-bundle-v1"


class CountWithPct(BaseModel):
    count: int
    pct: float | None = None


class ReasonCount(BaseModel):
    reason: str
    count: int


class CandidateFunnelMarketsReport(BaseModel):
    total: int
    by_platform: dict[str, int] = Field(default_factory=dict)
    open: CountWithPct
    closed: CountWithPct
    with_outcome_prices: CountWithPct
    with_token_ids: CountWithPct
    with_usable_deadlines: CountWithPct
    with_compiled_contracts: CountWithPct


class CandidateFunnelCompilationReport(BaseModel):
    compiled: CountWithPct
    below_compiler_confidence: CountWithPct
    missing_source_deadline_conditions: CountWithPct
    compiler_abstention_or_error: CountWithPct


class CandidateFunnelIdentityReport(BaseModel):
    identity_links: int
    verified: CountWithPct
    ambiguous: CountWithPct
    unresolved: CountWithPct
    rejected: CountWithPct
    false_equivalence: CountWithPct
    top_blocking_reasons: list[ReasonCount] = Field(default_factory=list)
    cluster_count: int
    average_cluster_size: float
    clusters_with_tradeable_pairs: int


class CandidateFunnelRelationReport(BaseModel):
    relation_proposals: int
    logical_relations: int
    logical_relation_sets: int
    confirmed_semantic: int
    semantic_veto: int
    semantic_abstention: int
    tradeable_true: int
    tradeable_false: int
    relation_types: dict[str, int] = Field(default_factory=dict)
    top_blocking_reasons: list[ReasonCount] = Field(default_factory=list)
    # Hypothesis generator breakdown (added by Ω upgrade)
    frame_proposals: int = 0
    hypothesis_proposals: int = 0
    hypotheses_by_type: dict[str, int] = Field(default_factory=dict)
    tradeable_by_hypothesis: int = 0
    tradeable_by_frame: int = 0


class SolverDecisionEntry(BaseModel):
    relation_key: str
    relation_kind: str
    relation_type: str
    market_ids: list[str] = Field(default_factory=list)
    identity_status: str
    solver_called: bool
    solver_skip_reason: str | None = None
    solver_none_reason: str | None = None
    proof_status: str | None = None
    valid_state_count: int = 0
    impossible_state_count: int = 0
    displayed_edge: float | None = None
    executable_edge: float | None = None
    worst_case_payoff: float | None = None
    false_arbitrage_label: str | None = None
    min_profit_threshold: float
    rejected_by_threshold: bool
    rejected_by_identity: bool
    rejected_by_false_arbitrage: bool
    rejected_by_dedup: bool


class CandidateFunnelSolverReport(BaseModel):
    total_considered: int
    solver_called: int
    solver_not_called: int
    returned_none: int
    produced_proof: int
    proof_status_distribution: dict[str, int] = Field(default_factory=dict)
    false_arbitrage_labels: dict[str, int] = Field(default_factory=dict)
    threshold_rejects: int
    decisions: list[SolverDecisionEntry] = Field(default_factory=list)


class CandidateFunnelPersistenceReport(BaseModel):
    solver_results: int
    above_threshold: int
    rejected_false_arbitrage: int
    duplicate_dedup: int
    persisted_candidates: int
    persistence_failures: int


class CandidateFunnelPreviewReport(BaseModel):
    positive_displayed_edge: int
    positive_executable_edge: int
    failed_only_execution_evidence_missing: int
    failed_only_identity_unverified: int
    failed_only_profit_below_threshold: int


class CandidateFunnelReport(BaseModel):
    run_id: str
    generated_at: datetime
    markets: CandidateFunnelMarketsReport
    compilation: CandidateFunnelCompilationReport
    identity: CandidateFunnelIdentityReport
    relations: CandidateFunnelRelationReport
    solver: CandidateFunnelSolverReport
    persistence: CandidateFunnelPersistenceReport
    preview: CandidateFunnelPreviewReport
    top_blockers: list[ReasonCount] = Field(default_factory=list)
    report_version: str = "candidate-funnel-v1"


class ShadowCandidateRow(BaseModel):
    observation_id: str
    run_id: str
    relation_key: str
    relation_kind: str
    relation_type: str
    market_ids: list[str] = Field(default_factory=list)
    displayed_edge: float | None = None
    executable_edge: float | None = None
    worst_case_payoff: float | None = None
    blocking_gates: list[str] = Field(default_factory=list)
    minimal_relaxation: list[str] = Field(default_factory=list)
    dangerous_relaxation: bool = False
    relaxation_flags: dict[str, bool] = Field(default_factory=dict)
    identity_status: str
    proof_status: str
    tradeable_relation: bool
    false_arbitrage_label: str | None = None
    rejected_by_threshold: bool = False
    rejected_by_dedup: bool = False
    execution_evidence_missing: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class ShadowCandidateListResponse(BaseModel):
    run_id: str
    generated_at: datetime
    total: int
    rows: list[ShadowCandidateRow] = Field(default_factory=list)
    report_version: str = "shadow-candidates-v1"


class SensitivityBucket(BaseModel):
    label: str
    count: int


class SensitivityReport(BaseModel):
    run_id: str
    generated_at: datetime
    min_profit_thresholds: list[SensitivityBucket] = Field(default_factory=list)
    identity_gates: list[SensitivityBucket] = Field(default_factory=list)
    semantic_thresholds: list[SensitivityBucket] = Field(default_factory=list)
    execution_modes: list[SensitivityBucket] = Field(default_factory=list)
    diagnostic_only: bool = True
    report_version: str = "candidate-sensitivity-v1"
