import type {
  CalibrationStatusResponse,
  CandidateFunnelReport,
  CertificateListResponse,
  AuditEvent,
  AutopsyRecord,
  BacktestReplayReport,
  CandidateDetail,
  CandidateSummary,
  DecisionLedgerEntry,
  DecisionSnapshot,
  EvaluationReport,
  ExecutionReport,
  IdentityClusterDetailResponse,
  IdentityClusterQueueResponse,
  IdentityReviewQueueResponse,
  LogicalRelationSet,
  MarketDetail,
  OpsMetrics,
  PolicyReport,
  PositionDetail,
  PositionSummary,
  ReadinessReport,
  RelationSetListResponse,
  RunProof,
  RunProofListResponse,
  ScorecardListResponse,
  SensitivityReport,
  ShadowCandidateListResponse,
  SettlementRequest,
  StrategyKillListResponse,
  TradeProofCertificate,
} from "../types";

const API_TOKEN = import.meta.env.VITE_PARALLAX_API_TOKEN?.trim();

function buildHeaders(headers?: Record<string, string>): Record<string, string> {
  return API_TOKEN ? { ...headers, Authorization: `Bearer ${API_TOKEN}` } : (headers ?? {});
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: buildHeaders() });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export const api = {
  runtime: {
    ready: () => get<ReadinessReport>("/ready"),
  },
  candidates: {
    list: () => get<CandidateSummary[]>("/api/candidates"),
    get: (id: string) => get<CandidateDetail>(`/api/candidates/${id}`),
    decision: (id: string) => get<DecisionSnapshot>(`/api/candidates/${id}/decision`),
    decisionLedger: (id: string, limit = 50) =>
      get<DecisionLedgerEntry[]>(`/api/candidates/${id}/decision-ledger?limit=${limit}`),
    certificate: (id: string) => get<TradeProofCertificate>(`/api/candidates/${id}/certificate`),
    issueCertificate: (id: string) => post<TradeProofCertificate>(`/api/candidates/${id}/certificate/issue`, {}),
    autopsy: (id: string) => get<AutopsyRecord[]>(`/api/candidates/${id}/autopsy`),
  },
  audit: {
    list: (limit = 100) => get<AuditEvent[]>(`/api/audit?limit=${limit}`),
    byEntity: (entityType: string, entityId: string) =>
      get<AuditEvent[]>(`/api/audit/${entityType}/${entityId}`),
  },
  markets: {
    get: (id: string) => get<MarketDetail>(`/api/markets/${id}`),
  },
  ops: {
    metrics: () => get<OpsMetrics>("/api/ops/metrics"),
    runs: () => get<RunProofListResponse>("/api/ops/runs"),
    run: (runId: string) => get<RunProof>(`/api/ops/runs/${runId}`),
    evaluation: () => get<EvaluationReport>("/api/ops/evaluation"),
    backtest: () => get<BacktestReplayReport>("/api/ops/backtest"),
    identityReview: () => get<IdentityReviewQueueResponse>("/api/ops/identity-review"),
    identityClusters: () => get<IdentityClusterQueueResponse>("/api/ops/identity-clusters"),
    identityCluster: (id: string) => get<IdentityClusterDetailResponse>(`/api/ops/identity-clusters/${id}`),
    calibration: () => get<CalibrationStatusResponse>("/api/ops/calibration"),
    activePolicy: () => get<CalibrationStatusResponse>("/api/ops/policy/active"),
    scorecards: () => get<ScorecardListResponse>("/api/ops/scorecards"),
    strategyKillList: () => get<StrategyKillListResponse>("/api/ops/strategy-kill-list"),
    certificates: () => get<CertificateListResponse>("/api/ops/certificates"),
    policy: () => get<PolicyReport>("/api/ops/policy"),
    execution: () => get<ExecutionReport>("/api/ops/execution"),
    relationSets: () => get<RelationSetListResponse>("/api/ops/relation-sets"),
    relationSet: (setKey: string) => get<LogicalRelationSet>(`/api/ops/relation-sets/${encodeURIComponent(setKey)}`),
    candidateFunnel: () => get<CandidateFunnelReport>("/api/ops/candidate-funnel"),
    shadowCandidates: (limit = 20) => get<ShadowCandidateListResponse>(`/api/ops/shadow-candidates?limit=${limit}`),
    sensitivity: () => get<SensitivityReport>("/api/ops/sensitivity"),
  },
  positions: {
    list: (status?: string) =>
      get<PositionSummary[]>(status ? `/api/positions?status=${status}` : "/api/positions"),
    get: (id: string) => get<PositionDetail>(`/api/positions/${id}`),
    settle: (id: string, payload: SettlementRequest) =>
      post<AutopsyRecord>(`/api/positions/${id}/settle`, payload),
  },
};
