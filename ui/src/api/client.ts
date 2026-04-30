import type { AuditEvent, CandidateDetail, CandidateSummary } from "../types";

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export const api = {
  candidates: {
    list: () => get<CandidateSummary[]>("/api/candidates"),
    get: (id: string) => get<CandidateDetail>(`/api/candidates/${id}`),
  },
  audit: {
    list: (limit = 100) => get<AuditEvent[]>(`/api/audit?limit=${limit}`),
  },
};
