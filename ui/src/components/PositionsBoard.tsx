import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import type {
  AutopsyRecord,
  PositionDetail,
  PositionSummary,
  SettlementRequest,
} from "../types";

const cardStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

const inputStyle: CSSProperties = {
  width: "100%",
  borderRadius: 10,
  border: "1px solid rgba(148, 163, 184, 0.22)",
  background: "rgba(2, 6, 23, 0.5)",
  color: "#ecf4ff",
  padding: "10px 12px",
};

export function PositionsBoard() {
  const [positions, setPositions] = useState<PositionSummary[]>([]);
  const [selected, setSelected] = useState<PositionDetail | null>(null);
  const [status, setStatus] = useState<string>("OPEN");
  const [loading, setLoading] = useState(true);
  const [settlementState, setSettlementState] = useState<SettlementRequest>({
    actual_pnl: 0.01,
    actual_resolution: {},
    resolution_type: "CORRECT",
    labels: [],
  });
  const [autopsy, setAutopsy] = useState<AutopsyRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.positions
      .list(status === "ALL" ? undefined : status)
      .then(async (rows) => {
        setPositions(rows);
        if (rows.length === 0) {
          setSelected(null);
          return;
        }
        const next = rows[0];
        const detail = await api.positions.get(next.id);
        setSelected(detail);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [status]);

  const selectPosition = async (positionId: string) => {
    setError(null);
    try {
      const detail = await api.positions.get(positionId);
      setSelected(detail);
      setAutopsy(null);
      setSettlementState({
        actual_pnl: detail.actual_pnl ?? 0.01,
        actual_resolution: Object.fromEntries(detail.legs.map((leg) => [leg.market_id, "YES"])),
        resolution_type: "CORRECT",
        labels: [],
      });
    } catch (e) {
      setError(String(e));
    }
  };

  const submitSettlement = async () => {
    if (!selected || selected.status !== "OPEN") return;
    setError(null);
    try {
      const record = await api.positions.settle(selected.id, settlementState);
      setAutopsy(record);
      await selectPosition(selected.id);
      const rows = await api.positions.list(status === "ALL" ? undefined : status);
      setPositions(rows);
    } catch (e) {
      setError(String(e));
    }
  };

  if (loading) return <p>Loading positions…</p>;
  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(300px, 420px) minmax(0, 1fr)",
        gap: 16,
      }}
    >
      <section style={cardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Paper Positions</h2>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            style={{ ...inputStyle, width: 120, padding: "8px 10px" }}
          >
            <option value="OPEN">OPEN</option>
            <option value="CLOSED">CLOSED</option>
            <option value="ALL">ALL</option>
          </select>
        </div>
        {positions.length === 0 ? (
          <p style={{ color: "#9fb4ca" }}>No positions for this filter.</p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {positions.map((position) => {
              const active = selected?.id === position.id;
              return (
                <button
                  key={position.id}
                  onClick={() => void selectPosition(position.id)}
                  style={{
                    textAlign: "left",
                    borderRadius: 14,
                    border: active ? "1px solid #7dd3fc" : "1px solid rgba(148, 163, 184, 0.18)",
                    background: active ? "rgba(125, 211, 252, 0.12)" : "rgba(2, 6, 23, 0.35)",
                    color: "#ecf4ff",
                    padding: 14,
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{position.status}</strong>
                    <span>{position.actual_pnl == null ? "Unsettled" : `${(position.actual_pnl * 100).toFixed(2)}%`}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "#9fb4ca", marginTop: 6 }}>
                    Candidate {position.candidate_id.slice(0, 8)} · {new Date(position.opened_at).toLocaleString()}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section style={cardStyle}>
        {!selected ? (
          <p style={{ color: "#9fb4ca" }}>Select a position to inspect its legs and settlement state.</p>
        ) : (
          <div style={{ display: "grid", gap: 18 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 18 }}>Position Detail</h2>
              <p style={{ color: "#9fb4ca" }}>
                Candidate {selected.candidate_id} · opened {new Date(selected.opened_at).toLocaleString()}
              </p>
            </div>

            <div style={{ display: "grid", gap: 10 }}>
              {selected.legs.map((leg) => (
                <div
                  key={`${leg.market_id}-${leg.side}`}
                  style={{
                    border: "1px solid rgba(148, 163, 184, 0.16)",
                    borderRadius: 12,
                    padding: 12,
                    background: "rgba(2, 6, 23, 0.28)",
                  }}
                >
                  <strong>{leg.side}</strong> {leg.market_id}
                  <div style={{ color: "#9fb4ca", marginTop: 4 }}>
                    platform {leg.platform ?? "unknown"} · price {leg.price.toFixed(3)}
                  </div>
                </div>
              ))}
            </div>

            {selected.status === "OPEN" ? (
              <div style={{ display: "grid", gap: 12 }}>
                <h3 style={{ margin: 0, fontSize: 16 }}>Settle Position</h3>
                <label style={{ display: "grid", gap: 6 }}>
                  <span>Actual PnL</span>
                  <input
                    type="number"
                    step="0.001"
                    value={settlementState.actual_pnl}
                    onChange={(e) =>
                      setSettlementState((current) => ({
                        ...current,
                        actual_pnl: Number(e.target.value),
                      }))
                    }
                    style={inputStyle}
                  />
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span>Resolution Type</span>
                  <select
                    value={settlementState.resolution_type}
                    onChange={(e) =>
                      setSettlementState((current) => ({
                        ...current,
                        resolution_type: e.target.value as SettlementRequest["resolution_type"],
                      }))
                    }
                    style={inputStyle}
                  >
                    <option value="CORRECT">CORRECT</option>
                    <option value="IDENTITY_ERROR">IDENTITY_ERROR</option>
                    <option value="ORACLE_DIVERGENCE">ORACLE_DIVERGENCE</option>
                    <option value="CANCELLED">CANCELLED</option>
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span>Actual resolution JSON</span>
                  <textarea
                    rows={7}
                    value={JSON.stringify(settlementState.actual_resolution, null, 2)}
                    onChange={(e) => {
                      try {
                        setSettlementState((current) => ({
                          ...current,
                          actual_resolution: JSON.parse(e.target.value),
                        }));
                      } catch {
                        // Preserve the last valid JSON until the user completes the edit.
                      }
                    }}
                    style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
                  />
                </label>
                <button
                  onClick={() => void submitSettlement()}
                  style={{
                    borderRadius: 12,
                    border: "1px solid #7dd3fc",
                    background: "rgba(125, 211, 252, 0.16)",
                    color: "#ecfeff",
                    padding: "10px 14px",
                    cursor: "pointer",
                  }}
                >
                  Settle and record autopsy
                </button>
              </div>
            ) : (
              <div>
                <h3 style={{ margin: 0, fontSize: 16 }}>Settlement</h3>
                <p style={{ color: "#9fb4ca" }}>
                  Closed {selected.closed_at ? new Date(selected.closed_at).toLocaleString() : "unknown"} · actual pnl{" "}
                  {selected.actual_pnl == null ? "n/a" : `${(selected.actual_pnl * 100).toFixed(2)}%`}
                </p>
              </div>
            )}

            {autopsy && (
              <div
                style={{
                  borderRadius: 14,
                  border: "1px solid rgba(74, 222, 128, 0.28)",
                  background: "rgba(20, 83, 45, 0.24)",
                  padding: 14,
                }}
              >
                <strong>Autopsy recorded</strong>
                <div style={{ color: "#c7ead6", marginTop: 6 }}>
                  {autopsy.resolution_type} · identity error {autopsy.identity_error ? "yes" : "no"}
                </div>
                {autopsy.labels.length > 0 && (
                  <div style={{ color: "#c7ead6", marginTop: 6 }}>
                    labels: {autopsy.labels.join(", ")}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
