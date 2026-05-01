import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CandidateDetail as ICandidateDetail } from "../types";

interface Props {
  candidateId: string;
  onClose: () => void;
}

export function CandidateDetail({ candidateId, onClose }: Props) {
  const [detail, setDetail] = useState<ICandidateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.candidates
      .get(candidateId)
      .then(setDetail)
      .catch((e: unknown) => setError(String(e)));
  }, [candidateId]);

  if (error) return <p style={{ color: "red" }}>Error: {error}</p>;
  if (!detail) return <p>Loading…</p>;

  const { payoff_matrix: m } = detail;

  return (
    <div>
      <button onClick={onClose}>← Back</button>
      <h2>{detail.opportunity_type}</h2>
      <p>Decision: <strong>{detail.court_decision}</strong></p>
      <p>Markets: {detail.market_ids.join(", ")}</p>

      <h3>Payoff Matrix</h3>
      <p>Total cost: {m.total_cost.toFixed(4)}</p>
      <p>Worst case: {(m.worst_case_payoff * 100).toFixed(2)}%</p>
      <p>Best case: {(m.best_case_payoff * 100).toFixed(2)}%</p>
      <p>Friction: {m.friction_bps} bps</p>

      <h4>Legs</h4>
      <ul>
        {m.legs.map((leg, i) => (
          <li key={i}>
            {leg.platform}:{leg.market_id} — {leg.side} @ {leg.price.toFixed(3)}
          </li>
        ))}
      </ul>

      <h4>Scenarios</h4>
      <ul>
        {m.scenarios.map((s, i) => (
          <li key={i} style={{ color: s.is_breaking ? "red" : "inherit" }}>
            {s.name}: {(s.payoff * 100).toFixed(2)}%
            {s.is_breaking && " ⚠ breaking"}
          </li>
        ))}
      </ul>

      {detail.risk_score && (
        <>
          <h3>Risk</h3>
          <p>Oracle: {detail.risk_score.oracle_risk.toFixed(2)}</p>
          <p>Deadline: {detail.risk_score.deadline_risk.toFixed(2)}</p>
          <p>Semantic: {detail.risk_score.semantic_risk.toFixed(2)}</p>
          <p>Composite: {detail.risk_score.composite.toFixed(2)}</p>
        </>
      )}
    </div>
  );
}
