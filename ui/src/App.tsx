import { useState } from "react";
import { AuditLog } from "./components/AuditLog";
import { CandidateDetail } from "./components/CandidateDetail";
import { ProofFeed } from "./components/ProofFeed";

type Tab = "feed" | "audit";

export function App() {
  const [tab, setTab] = useState<Tab>("feed");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div style={{ fontFamily: "monospace", maxWidth: 1200, margin: "0 auto", padding: 16 }}>
      <h1>PARALLAX — War Room</h1>

      {selectedId ? (
        <CandidateDetail
          candidateId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      ) : (
        <>
          <nav style={{ marginBottom: 16 }}>
            <button onClick={() => setTab("feed")} disabled={tab === "feed"}>
              Proof Feed
            </button>{" "}
            <button onClick={() => setTab("audit")} disabled={tab === "audit"}>
              Audit Log
            </button>
          </nav>

          {tab === "feed" && <ProofFeed onSelect={setSelectedId} />}
          {tab === "audit" && <AuditLog />}
        </>
      )}
    </div>
  );
}
