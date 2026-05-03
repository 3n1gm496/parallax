import { useEffect, useState, type CSSProperties } from "react";

import { api } from "../api/client";
import type { BacktestReplayReport, LogicalRelationSet } from "../types";

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

const cardStyle: CSSProperties = {
  borderRadius: 16,
  border: "1px solid rgba(148, 163, 184, 0.16)",
  background: "rgba(2, 6, 23, 0.35)",
  padding: 16,
};

function formatMetric(value: number | null | undefined, digits = 4): string {
  if (value == null || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

function formatWhen(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "n/a";
}

function renderCounts(entries: Record<string, number>) {
  const rows = Object.entries(entries).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return <span style={{ color: "#9fb4ca" }}>No data.</span>;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {rows.map(([label, count]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <span style={{ color: "#9fb4ca" }}>{label}</span>
          <strong>{count}</strong>
        </div>
      ))}
    </div>
  );
}

export function RelationSetsView() {
  const [relationSets, setRelationSets] = useState<LogicalRelationSet[]>([]);
  const [selected, setSelected] = useState<LogicalRelationSet | null>(null);
  const [backtest, setBacktest] = useState<BacktestReplayReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.ops.relationSets(), api.ops.backtest()])
      .then(([relationSetPayload, backtestPayload]) => {
        if (cancelled) return;
        setRelationSets(relationSetPayload.items);
        setSelected(relationSetPayload.items[0] ?? null);
        setBacktest(backtestPayload);
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

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    api.ops
      .relationSet(selected.set_key)
      .then((payload) => {
        if (!cancelled) setSelected(payload);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.set_key]);

  if (loading) return <p>Loading relation sets…</p>;
  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;

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
        <MetricCard label="Relation sets" value={String(relationSets.length)} />
        <MetricCard label="Settled replays" value={String(backtest?.settled_positions ?? 0)} />
        <MetricCard label="Replay win rate" value={formatMetric(backtest?.realized_win_rate)} />
        <MetricCard label="False positive rate" value={formatMetric(backtest?.false_positive_rate)} />
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "minmax(320px, 0.95fr) minmax(0, 1.35fr)", gap: 16 }}>
        <div style={panelStyle}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Relation Set Catalog</h2>
          <p style={{ color: "#9fb4ca" }}>
            Dedicated drill-down for persisted n-ary proofs. Select a set to inspect membership and semantic pair reviews.
          </p>
          {relationSets.length === 0 ? (
            <p style={{ color: "#9fb4ca" }}>No persisted relation sets.</p>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {relationSets.map((item) => {
                const active = selected?.set_key === item.set_key;
                return (
                  <button
                    key={item.relation_set_id ?? item.set_key}
                    onClick={() => setSelected(item)}
                    style={{
                      textAlign: "left",
                      cursor: "pointer",
                      borderRadius: 14,
                      border: active ? "1px solid #7dd3fc" : "1px solid rgba(148, 163, 184, 0.16)",
                      background: active ? "rgba(125, 211, 252, 0.08)" : "rgba(2, 6, 23, 0.35)",
                      color: "#ecf4ff",
                      padding: 14,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                      <strong>{item.relation_type}</strong>
                      <span style={{ color: "#9fb4ca" }}>{item.proof_status}</span>
                    </div>
                    <div style={{ color: "#bfd3ea", marginTop: 6 }}>{item.member_market_ids.join(" · ")}</div>
                    <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                      confidence {formatMetric(item.confidence)} · tradeable {String(item.tradeable_relation)}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Selected Set Detail</h2>
            {!selected ? (
              <p style={{ color: "#9fb4ca" }}>No relation set selected.</p>
            ) : (
              <div style={{ display: "grid", gap: 14 }}>
                <div style={{ color: "#bfd3ea" }}>
                  <strong>Set key</strong>: {selected.set_key}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                  <div style={cardStyle}>
                    <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Type</div>
                    <div style={{ fontSize: 24, marginTop: 8, fontWeight: 700 }}>{selected.relation_type}</div>
                  </div>
                  <div style={cardStyle}>
                    <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Status</div>
                    <div style={{ fontSize: 24, marginTop: 8, fontWeight: 700 }}>{selected.proof_status}</div>
                  </div>
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Members</div>
                  <div style={{ display: "grid", gap: 8 }}>
                    {selected.member_market_ids.map((memberId) => (
                      <div key={memberId} style={cardStyle}>
                        {memberId}
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Semantic pair reviews</div>
                  {Array.isArray(selected.evidence.semantic_pair_reviews) && selected.evidence.semantic_pair_reviews.length > 0 ? (
                    <div style={{ display: "grid", gap: 10 }}>
                      {selected.evidence.semantic_pair_reviews.map((review, index) => {
                        const payload = review as Record<string, unknown>;
                        return (
                          <div key={`${String(payload.from_market_id)}-${String(payload.to_market_id)}-${index}`} style={cardStyle}>
                            <div style={{ color: "#dce7f5" }}>
                              <strong>{String(payload.from_market_id)}</strong> ↔ <strong>{String(payload.to_market_id)}</strong>
                            </div>
                            <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                              {String(payload.relation_type)} · proof {String(payload.proof_status)} · confidence {formatMetric(Number(payload.confidence))}
                            </div>
                            <div style={{ color: "#bfd3ea", marginTop: 6 }}>{String(payload.reasoning)}</div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <span style={{ color: "#9fb4ca" }}>No pair review detail persisted.</span>
                  )}
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Raw evidence</div>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "#dce7f5" }}>
                    {JSON.stringify(selected.evidence, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Replay / Backtest Harness</h2>
            {!backtest ? (
              <p style={{ color: "#9fb4ca" }}>No replay report available.</p>
            ) : (
              <div style={{ display: "grid", gap: 14 }}>
                <div style={{ color: "#9fb4ca" }}>
                  generated {formatWhen(backtest.generated_at)} · version {backtest.report_version}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
                  <MetricCard label="Snapshots" value={String(backtest.total_snapshots)} />
                  <MetricCard label="With positions" value={String(backtest.snapshots_with_positions)} />
                  <MetricCard label="Avg stored edge" value={formatMetric(backtest.average_stored_edge)} />
                  <MetricCard label="Avg realized pnl" value={formatMetric(backtest.average_realized_pnl)} />
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Replay outcomes</div>
                  {renderCounts(backtest.outcomes_by_type)}
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Recent replay rows</div>
                  {backtest.rows.length === 0 ? (
                    <span style={{ color: "#9fb4ca" }}>No replay rows.</span>
                  ) : (
                    <div style={{ display: "grid", gap: 10 }}>
                      {backtest.rows.slice(0, 12).map((row) => (
                        <div key={`${row.candidate_id}-${row.snapshot_evaluated_at}`} style={cardStyle}>
                          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                            <strong>{row.opportunity_type}</strong>
                            <span style={{ color: "#9fb4ca" }}>{row.replay_outcome}</span>
                          </div>
                          <div style={{ color: "#bfd3ea", marginTop: 6 }}>{row.candidate_id}</div>
                          <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                            stored edge {formatMetric(row.stored_executable_edge)} · actual pnl {formatMetric(row.actual_pnl)} · capture {formatMetric(row.edge_capture_ratio)}
                          </div>
                          <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                            snapshot {formatWhen(row.snapshot_evaluated_at)} · run {row.snapshot_run_id ?? "n/a"}
                          </div>
                          {row.autopsy_labels.length > 0 && (
                            <div style={{ color: "#fca5a5", marginTop: 6 }}>labels: {row.autopsy_labels.join(", ")}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={cardStyle}>
      <div style={{ color: "#9fb4ca", fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 28, marginTop: 8, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
