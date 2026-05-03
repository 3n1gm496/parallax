import type {
  AuditEvent,
  AutopsyRecord,
  BacktestReplayReport,
  CandidateDetail,
  CandidateSummary,
  DecisionSnapshot,
  EvaluationReport,
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
  SettlementRequest,
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
    policy: () => get<PolicyReport>("/api/ops/policy"),
    relationSets: () => get<RelationSetListResponse>("/api/ops/relation-sets"),
    relationSet: (setKey: string) => get<LogicalRelationSet>(`/api/ops/relation-sets/${encodeURIComponent(setKey)}`),
  },
  positions: {
    list: (status?: string) =>
      get<PositionSummary[]>(status ? `/api/positions?status=${status}` : "/api/positions"),
    get: (id: string) => get<PositionDetail>(`/api/positions/${id}`),
    settle: (id: string, payload: SettlementRequest) =>
      post<AutopsyRecord>(`/api/positions/${id}/settle`, payload),
  },
};
