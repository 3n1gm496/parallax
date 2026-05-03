const API_TOKEN = import.meta.env.VITE_PARALLAX_API_TOKEN?.trim();

function buildHeaders(headers?: Record<string, string>): Record<string, string> {
  return API_TOKEN ? { ...headers, Authorization: `Bearer ${API_TOKEN}` } : (headers ?? {});
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: buildHeaders() });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export interface IdentityClusterEntry {
  cluster_id: string;
  cluster_key: string;
  identity_type: string;
  status: string;
  confidence: number;
  member_count: number;
  primary_market_id: string | null;
  primary_market_title: string | null;
  created_at: string;
}

export interface IdentityClusterQueueResponse {
  generated_at: string;
  clusters: IdentityClusterEntry[];
  total: number;
}

export interface IdentityMetricsReport {
  computed_at: string | null;
  scorer_version: string;
  cluster_count: number;
  verified_count: number;
  ambiguous_count: number;
  benchmark_accuracy: number | null;
  benchmark_total: number;
  benchmark_correct: number;
  benchmark_wrong: number;
}

export function fetchIdentityClusters(limit = 100): Promise<IdentityClusterQueueResponse> {
  return get<IdentityClusterQueueResponse>(`/api/ops/identity-clusters?limit=${limit}`);
}

export function fetchIdentityMetrics(): Promise<IdentityMetricsReport> {
  return get<IdentityMetricsReport>("/api/ops/identity-metrics");
}

export function recomputeIdentityMetrics(): Promise<{
  computed_at: string;
  cluster_count: number;
  benchmark_accuracy: number | null;
}> {
  return post("/api/ops/identity-metrics/recompute");
}
