export interface Leg {
  market_id: string;
  side: "YES" | "NO";
  price: number;
  quantity: number;
  cost: number | null;
  outcome: string | null;
  platform: string | null;
}

export interface Scenario {
  name: string;
  description: string;
  is_breaking: boolean;
  payoff: number;
}

export interface PayoffMatrix {
  legs: Leg[];
  total_cost: number;
  scenarios: Scenario[];
  worst_case_payoff: number;
  best_case_payoff: number;
  breaking_scenario: Scenario | null;
  opportunity_type: string;
  friction_bps: number;
}

export interface RiskScore {
  oracle_risk: number;
  deadline_risk: number;
  semantic_risk: number;
  execution_risk: number;
  liquidity_risk: number;
  cancellation_risk: number;
  source_trust_risk: number;
  composite: number;
  policy_version: string;
}

export interface SimulationResult {
  candidate_id: string;
  displayed_edge: number;
  executable_edge: number;
  simulated_pnl: number;
  friction_bps: number;
  fill_probability: number;
  is_executable: boolean;
  note: string;
  estimated_slippage_bps: number;
  estimated_slippage_cost: number;
  spread_cross_cost: number;
  stale_quote_cost: number;
  partial_fill_cost: number;
  non_execution_cost: number;
  execution_quality: "high" | "medium" | "low";
  risk_flags: string[];
  venue_breakdown: Record<string, unknown>;
  model_version: string;
  execution_model: "heuristic" | "snapshot_based" | "replay_based" | "degraded";
  quote_staleness_seconds: number | null;
  snapshot_ids: string[];
  depth_support: boolean | null;
  partial_fill_risk: number;
}

export interface DecisionGate {
  name: string;
  status: "pass" | "watchlist" | "reject" | "info";
  observed: string;
  threshold: string | null;
  detail: string | null;
}

export interface CourtAssessment {
  decision: string;
  simulated_pnl: number;
  fill_probability: number;
  composite_risk: number | null;
  reasons: string[];
  opportunity_type: string | null;
  relation_type: string | null;
  risk_flags: string[];
  gates: DecisionGate[];
  policy_version: string;
}

export interface RelationEvidence {
  from_market_id: string;
  to_market_id: string;
  relation_type: string;
  confidence: number;
  created_by: string;
  evidence_version: string;
  structural_relation_type: string | null;
  semantic_relation_type: string | null;
  semantic_confidence: number | null;
  semantic_reasoning: string | null;
  comparison_axes: string[];
  breaking_scenarios: Scenario[];
  oracle_alignment: string | null;
  deadline_alignment: string | null;
  source_alignment: string | null;
  ambiguity_terms: string[];
  relation_signals: Record<string, unknown>;
  identity_provenance: Record<string, unknown> | null;
  identity_status?: string;
  identity_confidence?: number | null;
  identity_version?: string;
  identity_blocking_reason?: string | null;
  proof_status?: string;
  tradeable_relation?: boolean;
  frame_id?: string | null;
  set_key?: string | null;
  member_market_ids?: string[];
}

export interface LogicalRelationSet {
  relation_set_id: string | null;
  set_key: string;
  member_market_ids: string[];
  relation_type: string;
  proof_status: "verified" | "rejected" | "needs_review";
  tradeable_relation: boolean;
  confidence: number;
  created_by: string;
  evidence: Record<string, unknown>;
  frame_id: string | null;
}

export interface CandidateSummary {
  id: string;
  opportunity_type: string;
  worst_case_payoff: number;
  total_cost: number;
  court_decision: string;
  created_at: string;
  execution_model: string | null;
}

export interface MarketSummary {
  id: string;
  platform: string;
  title: string;
  outcome_prices: number[];
  group_id: string | null;
  deadline: string;
  deadline_precision: "exact" | "inferred";
  data_provenance: "persisted";
  is_closed: boolean;
}

export interface MarketDetail extends MarketSummary {
  description: string;
  resolution_criteria: string;
  resolution_source: string | null;
  deadline_source: string | null;
  contract: unknown | null;
}

export interface CandidateDetail {
  id: string;
  opportunity_type: string;
  market_ids: string[];
  payoff_matrix: PayoffMatrix;
  risk_score: RiskScore | null;
  decision_snapshot: DecisionSnapshot | null;
  simulation_result: SimulationResult | null;
  court_assessment: CourtAssessment | null;
  relation_evidence: RelationEvidence | null;
  court_decision: string;
  created_at: string;
}

export interface DecisionSnapshot {
  candidate_id: string;
  run_id: string | null;
  risk_score: RiskScore | null;
  relation_evidence: RelationEvidence | null;
  simulation_result: SimulationResult | null;
  court_assessment: CourtAssessment | null;
  snapshot_version: string;
  evaluated_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  entity_type?: string;
  entity_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PositionSummary {
  id: string;
  candidate_id: string;
  status: string;
  opened_at: string;
  closed_at: string | null;
  actual_pnl: number | null;
}

export interface PositionDetail extends PositionSummary {
  legs: Leg[];
}

export interface AutopsyRecord {
  id: string;
  candidate_id: string;
  position_id: string | null;
  actual_resolution: Record<string, string>;
  resolution_type: string;
  identity_error: boolean;
  labels: string[];
  created_at: string;
}

export interface SettlementRequest {
  actual_pnl: number;
  actual_resolution: Record<string, string>;
  resolution_type: "CORRECT" | "IDENTITY_ERROR" | "ORACLE_DIVERGENCE" | "CANCELLED";
  labels: string[];
}

export interface RunSummary {
  run_id: string | null;
  run_status: string;
  started_at: string | null;
  completed_at: string | null;
  markets_ingested: number;
  market_counts_by_platform: Record<string, number>;
  contracts_compiled: number;
  events_resolved: number;
  relations_detected: number;
  candidates_found: number;
  candidates_watchlisted: number;
  positions_opened: number;
  positions_settled: number;
  config_fingerprint: string | null;
  provider_fingerprints: Record<string, string>;
  errors: string[];
}

export interface RunProof {
  run_id: string;
  run_status: string;
  started_at: string;
  completed_at: string | null;
  config_fingerprint: string;
  provider_fingerprints: Record<string, string>;
  readiness_checks: Record<string, unknown>;
  control_state: Record<string, unknown>;
  markets_ingested: number;
  market_counts_by_platform: Record<string, number>;
  contracts_compiled: number;
  events_resolved: number;
  relations_detected: number;
  candidates_found: number;
  candidates_watchlisted: number;
  positions_opened: number;
  positions_settled: number;
  fatal_errors: string[];
  non_fatal_errors: string[];
  proof_version: string;
}

export interface RunProofListResponse {
  runs: RunProof[];
}

export interface OpsActivityMetric {
  runs: number;
  latest_at: string | null;
  latest_payload: Record<string, unknown>;
}

export interface PipelineOpsMetrics {
  latest_pipeline_event_at: string | null;
  activity_metrics: Record<string, OpsActivityMetric>;
  candidate_evaluations_last_24h: number;
  positions_opened_last_24h: number;
  settlements_last_24h: number;
  recent_runs: RunSummary[];
}

export interface AuditOpsMetrics {
  total_events: number;
  events_last_24h: number;
  counts_by_event_type: Record<string, number>;
}

export interface AutopsyOpsMetrics {
  total_records: number;
  identity_errors: number;
  counts_by_resolution_type: Record<string, number>;
  counts_by_label: Record<string, number>;
  latest_autopsy_at: string | null;
}

export interface OpportunityEvaluationSummary {
  opportunity_type: string;
  settled_positions: number;
  profitable_settlements: number;
  realized_win_rate: number;
  average_expected_edge: number | null;
  average_realized_pnl: number | null;
  average_edge_capture_ratio: number | null;
  failure_labels: Record<string, number>;
}

export interface EvaluationOpsMetrics {
  settled_positions: number;
  profitable_settlements: number;
  unprofitable_settlements: number;
  realized_win_rate: number | null;
  average_expected_edge: number | null;
  average_realized_pnl: number | null;
  average_edge_capture_ratio: number | null;
  false_positive_rate: number | null;
  resolution_mix: Record<string, number>;
  failure_labels: Record<string, number>;
  opportunity_type_breakdown: OpportunityEvaluationSummary[];
  policy_version: string;
}

export interface EvaluationReport {
  generated_at: string;
  policy_version: string;
  metrics: EvaluationOpsMetrics;
  report_version: string;
}

export interface IdentityReviewQueueEntry {
  candidate_id: string;
  opportunity_type: string;
  expected_edge: number;
  ambiguity_severity: "low" | "medium" | "high";
  venue_mismatch_risk: number;
  autopsy_failure_pressure: number;
  relation_type: string | null;
  reasons: string[];
  queue_version: string;
}

export interface IdentityReviewQueueResponse {
  generated_at: string;
  items: IdentityReviewQueueEntry[];
  queue_version: string;
}

export interface RelationSetListResponse {
  items: LogicalRelationSet[];
}

export interface BacktestReplayRow {
  candidate_id: string;
  detected_at: string;
  opportunity_type: string;
  court_decision_at_snapshot: string | null;
  relation_type_at_snapshot: string | null;
  tradeable_relation_at_snapshot: boolean | null;
  identity_status_at_snapshot: string | null;
  snapshot_run_id: string | null;
  snapshot_evaluated_at: string;
  stored_executable_edge: number | null;
  stored_fill_probability: number | null;
  stored_composite_risk: number | null;
  position_status: string | null;
  position_opened_at: string | null;
  position_closed_at: string | null;
  actual_pnl: number | null;
  edge_capture_ratio: number | null;
  resolution_type: string | null;
  autopsy_labels: string[];
  replay_outcome: string;
}

export interface BacktestReplayReport {
  generated_at: string;
  total_snapshots: number;
  snapshots_with_positions: number;
  settled_positions: number;
  profitable_settlements: number;
  realized_win_rate: number | null;
  average_stored_edge: number | null;
  average_realized_pnl: number | null;
  average_edge_capture_ratio: number | null;
  false_positive_rate: number | null;
  outcomes_by_type: Record<string, number>;
  rows: BacktestReplayRow[];
  report_version: string;
}

export interface RelationQualityOpsMetrics {
  proposal_counts_by_type: Record<string, number>;
  logic_rejected_counts_by_type: Record<string, number>;
  semantic_veto_counts_by_type: Record<string, number>;
  false_positive_autopsy_by_relation_type: Record<string, number>;
  counterexample_hit_rate: number | null;
  counterexample_status_counts: Record<string, number>;
  tradeable_vs_nontradeable_ratio: number | null;
  verified_relation_counts_by_type: Record<string, number>;
  verified_relation_set_counts_by_type: Record<string, number>;
  policy_version: string;
}

export interface OpsMetrics {
  market_counts_by_platform: Record<string, number>;
  candidate_counts_by_decision: Record<string, number>;
  open_positions: number;
  latest_audit_at: string | null;
  latest_ingest_at: string | null;
  latest_candidate_at: string | null;
  pipeline: PipelineOpsMetrics;
  audit: AuditOpsMetrics;
  autopsy: AutopsyOpsMetrics;
  calibration: CalibrationOpsMetrics;
  evaluation: EvaluationOpsMetrics;
  relation_quality: RelationQualityOpsMetrics;
}

export interface CalibrationOpsMetrics {
  total_labeled_autopsies: number;
  label_rate_by_type: Record<string, number>;
  feedback_pressure_by_component: Record<string, number>;
  recommended_threshold_adjustments: Record<string, string>;
  policy_version: string;
}

export interface PolicyRecommendation {
  component: string;
  priority: "high" | "medium" | "low";
  pressure: number;
  current_value: number | null;
  recommended_value: number | null;
  action: string;
  basis: string[];
}

export interface PolicyReport {
  generated_at: string;
  policy_version: string;
  calibration_policy_version: string;
  identity_risk_pressure: number;
  semantic_risk_pressure: number;
  execution_risk_pressure: number;
  liquidity_risk_pressure: number;
  oracle_risk_pressure: number;
  review_queue_size: number;
  recent_identity_invalidations: number;
  recent_oracle_invalidations: number;
  recommendations: PolicyRecommendation[];
  report_version: string;
}

export interface ReadinessCheck {
  status: string;
  provider?: string;
  enabled?: boolean;
  configured?: boolean;
  market_count?: number;
  latest_market_at?: string | null;
  age_minutes?: number | null;
  freshness_threshold_minutes?: number;
  min_relation_confidence?: number;
  reason?: string | null;
}

export interface RuntimeControlState {
  global_pause: boolean;
  venue_pauses: Record<string, boolean>;
  semantic_analysis_disabled: boolean;
  live_execution_enabled: boolean;
  degraded_read_only_mode: boolean;
  operator_approval_required: boolean;
  max_exposure: number;
  max_daily_loss: number;
  max_candidate_concurrency: number;
  control_version: string;
}

export interface ReadinessReport {
  status: string;
  database: string;
  degraded_reasons: string[];
  controls: RuntimeControlState;
  checks: {
    semantic_analysis: ReadinessCheck;
    providers: Record<string, ReadinessCheck>;
  };
  orderbook_enabled: boolean;
  venue_token_count: number;
}

export interface ExecutionCoverageStats {
  platform: string;
  venue_token_count: number;
  snapshot_count: number;
  latest_snapshot_at: string | null;
}

export interface ExecutionReport {
  orderbook_enabled: boolean;
  coverage: ExecutionCoverageStats[];
  total_venue_tokens: number;
  total_snapshots: number;
  execution_model_distribution: Record<string, number>;
  avg_quote_staleness_seconds: number | null;
  depth_support_rate: number | null;
  report_basis: string;
}
