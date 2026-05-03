import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import type {
  AuditEvent,
  CandidateDetail,
  CandidateSummary,
  IdentityReviewQueueEntry,
  IdentityReviewQueueResponse,
} from "../types";

interface Props {
  onSelect: (candidateId: string) => void;
}

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

const queueStyle: CSSProperties = {
  borderRadius: 16,
  border: "1px solid rgba(148, 163, 184, 0.16)",
  background: "rgba(2, 6, 23, 0.35)",
  padding: 16,
};

type CandidateQueueRow = {
  candidateId: string;
  label: string;
  detail: string;
  tone?: string;
};

type AuditQueueRow = {
  entityId: string;
  label: string;
  detail: string;
};

function metricTone(count: number): string {
  if (count === 0) return "#86efac";
  if (count <= 2) return "#fde68a";
  return "#fca5a5";
}

export function TriageView({ onSelect }: Props) {
  const [candidateDetails, setCandidateDetails] = useState<CandidateDetail[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [identityReviewQueue, setIdentityReviewQueue] = useState<IdentityReviewQueueEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.candidates
      .list()
      .then(async (rows: CandidateSummary[]) => {
        const [details, audit, identityReview] = await Promise.all([
          Promise.all(rows.map((row) => api.candidates.get(row.id))),
          api.audit.list(200),
          api.ops.identityReview(),
        ]);
        if (!cancelled) {
          setCandidateDetails(details);
          setAuditEvents(audit);
          setIdentityReviewQueue((identityReview as IdentityReviewQueueResponse).items);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p>Loading triage queues…</p>;
  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;

  const ambiguousPairs = candidateDetails.flatMap((candidate) => {
    const assessmentText = candidate.court_assessment?.reasons.join(" ").toLowerCase() ?? "";
    const ambiguityTerms = candidate.relation_evidence?.ambiguity_terms ?? [];
    const ambiguityLevel = String(candidate.relation_evidence?.relation_signals?.ambiguity_level ?? "low");
    if (
      ambiguityLevel === "high" ||
      ambiguityTerms.length > 0 ||
      assessmentText.includes("ambiguity")
    ) {
      return [
        {
          candidateId: candidate.id,
          label: candidate.opportunity_type,
          detail: `${ambiguityLevel} ambiguity · ${ambiguityTerms.join(", ") || "manual review needed"}`,
          tone: "#fde68a",
        } satisfies CandidateQueueRow,
      ];
    }
    return [];
  });

  const highEdgeLowLiquidity = candidateDetails.flatMap((candidate) => {
    const simulation = candidate.simulation_result;
    if (!simulation) return [];
    if (simulation.displayed_edge >= 0.03 && (simulation.fill_probability < 0.55 || simulation.execution_quality === "low")) {
      return [
        {
          candidateId: candidate.id,
          label: candidate.opportunity_type,
          detail: `displayed ${(simulation.displayed_edge * 100).toFixed(2)}% · executable ${(simulation.executable_edge * 100).toFixed(2)}% · fill ${(simulation.fill_probability * 100).toFixed(1)}%`,
          tone: "#fca5a5",
        } satisfies CandidateQueueRow,
      ];
    }
    return [];
  });

  const identityConflicts = identityReviewQueue.map((item) => ({
    candidateId: item.candidate_id,
    label: item.relation_type ?? item.opportunity_type,
    detail: `${item.ambiguity_severity} ambiguity · venue risk ${(item.venue_mismatch_risk * 100).toFixed(0)}% · ${item.reasons.join(" | ")}`,
    tone: item.ambiguity_severity === "high" ? "#fca5a5" : "#fde68a",
  }));

  const autopsyFailures = auditEvents.flatMap((event) => {
    if (event.event_type !== "position.settled") return [];
    const labels = Array.isArray(event.payload.labels) ? event.payload.labels.map(String) : [];
    if (labels.length === 0) return [];
    return [
      {
        entityId: event.entity_id ?? "unknown-position",
        label: String(event.payload.resolution_type ?? "UNKNOWN"),
        detail: `candidate ${String(event.payload.candidate_id ?? "n/a")} · labels ${labels.join(", ")}`,
      } satisfies AuditQueueRow,
    ];
  });

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section
        style={{
          ...panelStyle,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        {[
          ["Ambiguous pairs", ambiguousPairs.length],
          ["High-edge low-liquidity", highEdgeLowLiquidity.length],
          ["Identity conflicts", identityConflicts.length],
          ["Autopsy failures", autopsyFailures.length],
        ].map(([label, count]) => (
          <div key={String(label)} style={queueStyle}>
            <div style={{ color: "#9fb4ca", fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              {label}
            </div>
            <div style={{ fontSize: 30, marginTop: 10, fontWeight: 700, color: metricTone(Number(count)) }}>
              {count}
            </div>
          </div>
        ))}
      </section>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 16,
        }}
      >
        <QueuePanel
          title="Ambiguous Semantic Pairs"
          subtitle="Candidates whose relation evidence or court output still shows ambiguity pressure."
          rows={ambiguousPairs}
          onSelect={onSelect}
        />
        <QueuePanel
          title="High Edge / Low Liquidity"
          subtitle="Displayed edge looks good, executable edge or fill probability does not."
          rows={highEdgeLowLiquidity}
          onSelect={onSelect}
        />
        <QueuePanel
          title="Identity Conflicts"
          subtitle="Cross-platform relations needing provenance review or showing mismatch pressure."
          rows={identityConflicts}
          onSelect={onSelect}
        />
        <AuditQueuePanel
          title="Autopsy Failures"
          subtitle="Recent settlement outcomes with labels that should drive policy change."
          rows={autopsyFailures}
        />
      </div>
    </div>
  );
}

function QueuePanel({
  title,
  subtitle,
  rows,
  onSelect,
}: {
  title: string;
  subtitle: string;
  rows: CandidateQueueRow[];
  onSelect: (candidateId: string) => void;
}) {
  return (
    <section style={panelStyle}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>{title}</h2>
      <p style={{ color: "#9fb4ca", marginTop: 0 }}>{subtitle}</p>
      {rows.length === 0 ? (
        <p style={{ color: "#9fb4ca" }}>Queue empty.</p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {rows.map((row) => (
            <button
              key={`${row.candidateId}-${row.label}`}
              onClick={() => onSelect(row.candidateId)}
              style={{
                textAlign: "left",
                cursor: "pointer",
                borderRadius: 14,
                border: "1px solid rgba(148, 163, 184, 0.16)",
                background: "rgba(2, 6, 23, 0.35)",
                color: "#ecf4ff",
                padding: 14,
              }}
            >
              <div style={{ color: row.tone ?? "#ecf4ff", fontWeight: 700 }}>{row.label}</div>
              <div style={{ color: "#9fb4ca", marginTop: 6 }}>{row.candidateId}</div>
              <div style={{ color: "#dce7f5", marginTop: 6 }}>{row.detail}</div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function AuditQueuePanel({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle: string;
  rows: AuditQueueRow[];
}) {
  return (
    <section style={panelStyle}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>{title}</h2>
      <p style={{ color: "#9fb4ca", marginTop: 0 }}>{subtitle}</p>
      {rows.length === 0 ? (
        <p style={{ color: "#9fb4ca" }}>Queue empty.</p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {rows.map((row, index) => (
            <div
              key={`${row.entityId}-${row.label}-${index}`}
              style={{
                borderRadius: 14,
                border: "1px solid rgba(148, 163, 184, 0.16)",
                background: "rgba(2, 6, 23, 0.35)",
                color: "#ecf4ff",
                padding: 14,
              }}
            >
              <div style={{ fontWeight: 700 }}>{row.label}</div>
              <div style={{ color: "#9fb4ca", marginTop: 6 }}>{row.entityId}</div>
              <div style={{ color: "#dce7f5", marginTop: 6 }}>{row.detail}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
