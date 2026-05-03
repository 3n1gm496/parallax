import { useState, type CSSProperties } from "react";
import { AuditLog } from "./components/AuditLog";
import { CandidateDetail } from "./components/CandidateDetail";
import { OperationsView } from "./components/OperationsView";
import { PositionsBoard } from "./components/PositionsBoard";
import { ProofFeed } from "./components/ProofFeed";
import { RelationSetsView } from "./components/RelationSetsView";
import { TriageView } from "./components/TriageView";

type View = "feed" | "triage" | "operations" | "relations" | "positions" | "audit";

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  background:
    "radial-gradient(circle at top, rgba(125, 211, 252, 0.16), transparent 32%), linear-gradient(180deg, #04111d 0%, #0b1726 48%, #101826 100%)",
  color: "#ecf4ff",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace",
};

const frameStyle: CSSProperties = {
  maxWidth: 1280,
  margin: "0 auto",
  padding: "32px 20px 48px",
};

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.22)",
  background: "rgba(9, 18, 31, 0.82)",
  boxShadow: "0 24px 90px rgba(2, 6, 23, 0.35)",
  borderRadius: 20,
  backdropFilter: "blur(12px)",
};

export function App() {
  const [view, setView] = useState<View>("feed");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div style={shellStyle}>
      <div style={frameStyle}>
        <header
          style={{
            ...panelStyle,
            padding: 24,
            marginBottom: 20,
            display: "grid",
            gap: 14,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 16,
              alignItems: "flex-start",
              flexWrap: "wrap",
            }}
          >
            <div>
              <div style={{ color: "#7dd3fc", letterSpacing: "0.22em", fontSize: 12 }}>
                PARALLAX
              </div>
              <h1 style={{ margin: "6px 0 8px", fontSize: 32 }}>Lifecycle Console</h1>
              <p style={{ margin: 0, color: "#bfd3ea", maxWidth: 760, lineHeight: 1.5 }}>
                Runtime view for detection, triage, court gating, paper positions, settlement, and post-trade autopsy.
              </p>
            </div>
            <div
              style={{
                minWidth: 260,
                display: "grid",
                gap: 8,
                color: "#9fb4ca",
                fontSize: 13,
              }}
            >
              <span>Polymarket native, Kalshi native.</span>
              <span>Court assessments are computed live from relation evidence and execution heuristics.</span>
              <span>Triage queues highlight ambiguity, liquidity drag, identity conflicts, and autopsy pressure.</span>
            </div>
          </div>

          {!selectedId && (
            <nav style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {[
                ["feed", "Opportunity Feed"],
                ["triage", "Triage Queues"],
                ["operations", "Operations"],
                ["relations", "Relation Sets"],
                ["positions", "Positions"],
                ["audit", "Audit Trail"],
              ].map(([key, label]) => {
                const active = view === key;
                return (
                  <button
                    key={key}
                    onClick={() => setView(key as View)}
                    style={{
                      borderRadius: 999,
                      border: active ? "1px solid #7dd3fc" : "1px solid rgba(148, 163, 184, 0.22)",
                      background: active ? "rgba(125, 211, 252, 0.14)" : "rgba(15, 23, 42, 0.7)",
                      color: active ? "#ecfeff" : "#c7d7eb",
                      padding: "10px 14px",
                      cursor: "pointer",
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </nav>
          )}
        </header>

        {selectedId ? (
          <CandidateDetail candidateId={selectedId} onClose={() => setSelectedId(null)} />
        ) : (
          <>
            {view === "feed" && <ProofFeed onSelect={setSelectedId} />}
            {view === "triage" && <TriageView onSelect={setSelectedId} />}
            {view === "operations" && <OperationsView />}
            {view === "relations" && <RelationSetsView />}
            {view === "positions" && <PositionsBoard />}
            {view === "audit" && <AuditLog />}
          </>
        )}
      </div>
    </div>
  );
}
