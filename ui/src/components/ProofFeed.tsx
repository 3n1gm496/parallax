import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import type { CandidateSummary, TradeProofCertificate } from "../types";

interface Props {
  onSelect: (id: string) => void;
}

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

function decisionTone(decision: string): string {
  if (decision === "APPROVED") return "#86efac";
  if (decision === "WATCHLIST") return "#fde68a";
  if (decision === "PAPER_TRADE") return "#7dd3fc";
  return "#fca5a5";
}

export function ProofFeed({ onSelect }: Props) {
  const [candidates, setCandidates] = useState<CandidateSummary[]>([]);
  const [certificates, setCertificates] = useState<Record<string, TradeProofCertificate>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.candidates.list(), api.ops.certificates().catch(() => ({ items: [] }))])
      .then(([candidateRows, certificateRows]) => {
        setCandidates(candidateRows);
        setCertificates(
          Object.fromEntries(certificateRows.items.map((item) => [item.candidate_id, item])),
        );
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading candidates…</p>;
  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;
  if (candidates.length === 0) return <p>No open candidates.</p>;

  const approved = candidates.filter((candidate) => candidate.court_decision === "APPROVED").length;
  const watchlist = candidates.filter((candidate) => candidate.court_decision === "WATCHLIST").length;
  const issued = Object.values(certificates).filter((row) => row.certificate_status === "issued").length;

  return (
    <section style={panelStyle}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Opportunity Feed</h2>
          <p style={{ color: "#9fb4ca", marginBottom: 0 }}>
            Click a candidate to inspect payoff, risk, live court assessment, and autopsy trail.
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Metric label="Open" value={String(candidates.length)} />
          <Metric label="Approved" value={String(approved)} />
          <Metric label="Watchlist" value={String(watchlist)} />
          <Metric label="Issued" value={String(issued)} />
        </div>
      </div>

      <div style={{ display: "grid", gap: 10 }}>
        {candidates.map((candidate) => {
          const certificate = certificates[candidate.id] ?? null;
          const certificateStatus = certificate?.certificate_status ?? "no_proof";
          return (
          <button
            key={candidate.id}
            onClick={() => onSelect(candidate.id)}
            style={{
              cursor: "pointer",
              textAlign: "left",
              borderRadius: 16,
              border: "1px solid rgba(148, 163, 184, 0.18)",
              background: "rgba(2, 6, 23, 0.4)",
              color: "#ecf4ff",
              padding: 16,
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1.4fr) repeat(4, minmax(0, 0.8fr))",
                gap: 14,
                alignItems: "center",
              }}
            >
              <div>
                <div style={{ fontWeight: 700 }}>{candidate.opportunity_type}</div>
                <div style={{ color: "#9fb4ca", marginTop: 4, fontSize: 12 }}>
                  {candidate.id.slice(0, 8)} · {new Date(candidate.created_at).toLocaleString()}
                </div>
              </div>
              <Metric label="Worst PnL" value={`${(candidate.worst_case_payoff * 100).toFixed(2)}%`} />
              <Metric label="Capital" value={candidate.total_cost.toFixed(4)} />
              <Metric
                label="Decision"
                value={candidate.court_decision}
                tone={decisionTone(candidate.court_decision)}
              />
              <Metric label="Proof" value={certificateStatus} />
            </div>
          </button>
          );
        })}
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div
      style={{
        borderRadius: 12,
        background: "rgba(15, 23, 42, 0.9)",
        border: "1px solid rgba(148, 163, 184, 0.14)",
        padding: "10px 12px",
      }}
    >
      <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 4, letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ color: tone ?? "#ecf4ff", fontWeight: 700 }}>{value}</div>
    </div>
  );
}
