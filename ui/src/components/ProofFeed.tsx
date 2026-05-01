import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CandidateSummary } from "../types";

interface Props {
  onSelect: (id: string) => void;
}

export function ProofFeed({ onSelect }: Props) {
  const [candidates, setCandidates] = useState<CandidateSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.candidates
      .list()
      .then(setCandidates)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading candidates…</p>;
  if (error) return <p style={{ color: "red" }}>Error: {error}</p>;
  if (candidates.length === 0) return <p>No open candidates.</p>;

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th>Type</th>
          <th>Worst Payoff</th>
          <th>Cost</th>
          <th>Decision</th>
          <th>Detected</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((c) => (
          <tr
            key={c.id}
            onClick={() => onSelect(c.id)}
            style={{ cursor: "pointer" }}
          >
            <td>{c.opportunity_type}</td>
            <td>{(c.worst_case_payoff * 100).toFixed(2)}%</td>
            <td>{c.total_cost.toFixed(4)}</td>
            <td>{c.court_decision}</td>
            <td>{new Date(c.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
