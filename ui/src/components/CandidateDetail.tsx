import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import type {
  AuditEvent,
  AutopsyRecord,
  CandidateDetail as CandidateDetailType,
  MarketDetail,
  PositionSummary,
} from "../types";

interface Props {
  candidateId: string;
  onClose: () => void;
}

const cardStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

export function CandidateDetail({ candidateId, onClose }: Props) {
  const [detail, setDetail] = useState<CandidateDetailType | null>(null);
  const [autopsy, setAutopsy] = useState<AutopsyRecord[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [positions, setPositions] = useState<PositionSummary[]>([]);
  const [markets, setMarkets] = useState<MarketDetail[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([
      api.candidates.get(candidateId),
      api.candidates.autopsy(candidateId),
      api.audit.byEntity("candidate", candidateId),
      api.positions.list(),
    ])
      .then(async ([candidate, autopsyRows, auditRows, positionRows]) => {
        const marketRows = await Promise.all(candidate.market_ids.map((marketId) => api.markets.get(marketId)));
        setDetail(candidate);
        setAutopsy(autopsyRows);
        setAudit(auditRows);
        setPositions(positionRows.filter((row) => row.candidate_id === candidateId));
        setMarkets(marketRows);
      })
      .catch((e: unknown) => setError(String(e)));
  }, [candidateId]);

  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;
  if (!detail) return <p>Loading…</p>;

  const { payoff_matrix: matrix, simulation_result: simulation, risk_score: risk, court_assessment: assessment } = detail;
  const snapshot = detail.decision_snapshot;
  const storedSimulation = snapshot?.simulation_result ?? null;
  const storedAssessment = snapshot?.court_assessment ?? null;
  const storedRelation = snapshot?.relation_evidence ?? null;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <button
          onClick={onClose}
          style={{
            borderRadius: 999,
            border: "1px solid rgba(148, 163, 184, 0.22)",
            background: "rgba(15, 23, 42, 0.74)",
            color: "#ecf4ff",
            padding: "10px 14px",
            cursor: "pointer",
          }}
        >
          Back to feed
        </button>
        <div style={{ color: "#9fb4ca", alignSelf: "center" }}>
          Candidate {detail.id} · created {new Date(detail.created_at).toLocaleString()}
        </div>
      </div>

      <section style={{ ...cardStyle, display: "grid", gap: 18 }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(280px, 0.8fr)", gap: 18 }}>
          <div>
            <div style={{ color: "#7dd3fc", fontSize: 12, letterSpacing: "0.18em" }}>OPPORTUNITY</div>
            <h2 style={{ margin: "6px 0 8px" }}>{detail.opportunity_type}</h2>
            <p style={{ color: "#9fb4ca", margin: 0 }}>Markets: {detail.market_ids.join(", ")}</p>
          </div>
          <div
            style={{
              border: "1px solid rgba(148, 163, 184, 0.16)",
              borderRadius: 14,
              background: "rgba(2, 6, 23, 0.35)",
              padding: 14,
            }}
          >
            <Metric label="Stored decision" value={detail.court_decision} />
            <Metric label="Worst-case payoff" value={`${(matrix.worst_case_payoff * 100).toFixed(2)}%`} />
            <Metric label="Best-case payoff" value={`${(matrix.best_case_payoff * 100).toFixed(2)}%`} />
            <Metric label="Capital deployed" value={matrix.total_cost.toFixed(4)} />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
          <section style={cardStyle}>
            <h3 style={{ marginTop: 0 }}>Execution</h3>
            {snapshot && (
              <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 10, letterSpacing: "0.08em" }}>
                SNAPSHOT {snapshot.snapshot_version} · {new Date(snapshot.evaluated_at).toLocaleString()}
                {snapshot.run_id ? ` · run ${snapshot.run_id}` : ""}
              </div>
            )}
            {storedSimulation && (
              <div style={{ color: "#bfd3ea", marginBottom: 10 }}>
                persisted edge {(storedSimulation.executable_edge * 100).toFixed(2)}% · live edge{" "}
                {simulation ? `${(simulation.executable_edge * 100).toFixed(2)}%` : "n/a"}
              </div>
            )}
            {simulation ? (
              <>
                <Metric label="Displayed edge" value={`${(simulation.displayed_edge * 100).toFixed(2)}%`} />
                <Metric label="Executable edge" value={`${(simulation.executable_edge * 100).toFixed(2)}%`} />
                <Metric label="Simulated pnl" value={`${(simulation.simulated_pnl * 100).toFixed(2)}%`} />
                <Metric label="Fill probability" value={`${(simulation.fill_probability * 100).toFixed(1)}%`} />
                <Metric label="Executable" value={simulation.is_executable ? "yes" : "no"} />
                <Metric label="Execution quality" value={simulation.execution_quality} />
                <Metric label="Slippage" value={`${simulation.estimated_slippage_bps} bps`} />
                <Metric label="Model" value={simulation.model_version} />
                <Metric label="Exec model" value={simulation.execution_model ?? "heuristic"} />
                {simulation.depth_support !== null && simulation.depth_support !== undefined && (
                  <Metric label="Depth support" value={simulation.depth_support ? "yes" : "no"} />
                )}
                {simulation.quote_staleness_seconds !== null && simulation.quote_staleness_seconds !== undefined && (
                  <Metric label="Quote age" value={`${simulation.quote_staleness_seconds.toFixed(1)}s`} />
                )}
                {simulation.partial_fill_risk > 0 && (
                  <Metric label="Partial fill risk" value={`${(simulation.partial_fill_risk * 100).toFixed(1)}%`} />
                )}
                <div style={{ color: "#bfd3ea", marginBottom: 8 }}>
                  drag: spread {simulation.spread_cross_cost.toFixed(4)} · stale {simulation.stale_quote_cost.toFixed(4)} · partial{" "}
                  {simulation.partial_fill_cost.toFixed(4)} · non-execution {simulation.non_execution_cost.toFixed(4)}
                </div>
                <p style={{ color: "#9fb4ca", marginBottom: 0 }}>{simulation.note}</p>
                {simulation.risk_flags.length > 0 && (
                  <div style={{ color: "#bfd3ea", marginTop: 8 }}>
                    flags: {simulation.risk_flags.join(", ")}
                  </div>
                )}
                <pre style={{ whiteSpace: "pre-wrap", color: "#9fb4ca", marginBottom: 0 }}>
                  {JSON.stringify(simulation.venue_breakdown, null, 2)}
                </pre>
              </>
            ) : (
              <p style={{ color: "#9fb4ca" }}>No simulation result.</p>
            )}
          </section>

          <section style={cardStyle}>
            <h3 style={{ marginTop: 0 }}>Risk</h3>
            {risk ? (
              <>
                <Metric label="Oracle risk" value={risk.oracle_risk.toFixed(2)} />
                <Metric label="Deadline risk" value={risk.deadline_risk.toFixed(2)} />
                <Metric label="Semantic risk" value={risk.semantic_risk.toFixed(2)} />
                <Metric label="Execution risk" value={risk.execution_risk.toFixed(2)} />
                <Metric label="Liquidity risk" value={risk.liquidity_risk.toFixed(2)} />
                <Metric label="Cancellation risk" value={risk.cancellation_risk.toFixed(2)} />
                <Metric label="Source trust risk" value={risk.source_trust_risk.toFixed(2)} />
                <Metric label="Composite" value={risk.composite.toFixed(2)} />
                <Metric label="Policy version" value={risk.policy_version} />
              </>
            ) : (
              <p style={{ color: "#9fb4ca" }}>No stored risk score.</p>
            )}
          </section>

          <section style={cardStyle}>
            <h3 style={{ marginTop: 0 }}>Court</h3>
            {storedAssessment && (
              <div style={{ color: "#bfd3ea", marginBottom: 10 }}>
                persisted {storedAssessment.decision} · live {assessment ? assessment.decision : "n/a"}
              </div>
            )}
            {assessment ? (
              <>
                <Metric label="Decision" value={assessment.decision} />
                <Metric label="Simulated pnl" value={`${(assessment.simulated_pnl * 100).toFixed(2)}%`} />
                <Metric label="Fill probability" value={`${(assessment.fill_probability * 100).toFixed(1)}%`} />
                <Metric label="Composite risk" value={assessment.composite_risk == null ? "n/a" : assessment.composite_risk.toFixed(2)} />
                <Metric label="Relation type" value={assessment.relation_type ?? "n/a"} />
                <Metric label="Policy version" value={assessment.policy_version} />
                {assessment.risk_flags.length > 0 && (
                  <div style={{ color: "#bfd3ea", marginBottom: 10 }}>
                    flags: {assessment.risk_flags.join(", ")}
                  </div>
                )}
                {assessment.gates.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 6, letterSpacing: "0.08em" }}>
                      GATES
                    </div>
                    <div style={{ display: "grid", gap: 6 }}>
                      {assessment.gates.map((gate) => (
                        <div key={`${gate.name}-${gate.status}`} style={{ color: "#dce7f5", fontSize: 13 }}>
                          <strong>{gate.name}</strong>: {gate.status} · observed {gate.observed}
                          {gate.threshold ? ` · threshold ${gate.threshold}` : ""}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div style={{ marginTop: 10 }}>
                  <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 6, letterSpacing: "0.08em" }}>
                    REASONS
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 18, color: "#dce7f5" }}>
                    {assessment.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              </>
            ) : (
              <p style={{ color: "#9fb4ca" }}>No live court assessment.</p>
            )}
          </section>
        </div>

        <section style={cardStyle}>
          <h3 style={{ marginTop: 0 }}>Market Runtime State</h3>
          <div style={{ display: "grid", gap: 10 }}>
            {markets.map((market) => (
              <div
                key={market.id}
                style={{
                  borderRadius: 12,
                  padding: 12,
                  border: "1px solid rgba(148, 163, 184, 0.16)",
                  background: "rgba(2, 6, 23, 0.28)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <strong>{market.id}</strong>
                  <span style={{ color: "#9fb4ca" }}>{market.platform}</span>
                </div>
                <div style={{ color: "#dce7f5", marginTop: 6 }}>{market.title}</div>
                <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                  deadline {new Date(market.deadline).toLocaleString()} · precision {market.deadline_precision}
                </div>
                {market.deadline_source && (
                  <div style={{ color: "#bfd3ea", marginTop: 4 }}>
                    inferred from {market.deadline_source}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 16 }}>
        <section style={cardStyle}>
          <h3 style={{ marginTop: 0 }}>Legs and Scenarios</h3>
          <div style={{ display: "grid", gap: 10, marginBottom: 16 }}>
            {matrix.legs.map((leg) => (
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
          <div style={{ display: "grid", gap: 10 }}>
            {matrix.scenarios.map((scenario) => (
              <div
                key={scenario.name}
                style={{
                  borderRadius: 12,
                  padding: 12,
                  border: scenario.is_breaking
                    ? "1px solid rgba(252, 165, 165, 0.35)"
                    : "1px solid rgba(148, 163, 184, 0.16)",
                  background: scenario.is_breaking ? "rgba(127, 29, 29, 0.18)" : "rgba(2, 6, 23, 0.28)",
                }}
              >
                <strong>{scenario.name}</strong>
                <div style={{ color: "#9fb4ca", margin: "6px 0" }}>{scenario.description}</div>
                <div>{(scenario.payoff * 100).toFixed(2)}%</div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ display: "grid", gap: 16 }}>
          <section style={cardStyle}>
            <h3 style={{ marginTop: 0 }}>Positions</h3>
            {positions.length === 0 ? (
              <p style={{ color: "#9fb4ca" }}>No paper positions opened for this candidate.</p>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {positions.map((position) => (
                  <div
                    key={position.id}
                    style={{
                      borderRadius: 12,
                      padding: 12,
                      border: "1px solid rgba(148, 163, 184, 0.16)",
                      background: "rgba(2, 6, 23, 0.28)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <strong>{position.status}</strong>
                      <span>{position.actual_pnl == null ? "Unsettled" : `${(position.actual_pnl * 100).toFixed(2)}%`}</span>
                    </div>
                    <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                      opened {new Date(position.opened_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section style={cardStyle}>
            <h3 style={{ marginTop: 0 }}>Autopsy and Audit</h3>
            {autopsy.length === 0 ? (
              <p style={{ color: "#9fb4ca" }}>No autopsy records yet.</p>
            ) : (
              <div style={{ display: "grid", gap: 10, marginBottom: 14 }}>
                {autopsy.map((record) => (
                  <div
                    key={record.id}
                    style={{
                      borderRadius: 12,
                      padding: 12,
                      border: "1px solid rgba(148, 163, 184, 0.16)",
                      background: "rgba(2, 6, 23, 0.28)",
                    }}
                  >
                    <strong>{record.resolution_type}</strong>
                    <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                      identity error {record.identity_error ? "yes" : "no"} · {new Date(record.created_at).toLocaleString()}
                    </div>
                    {record.labels.length > 0 && (
                      <div style={{ color: "#bfd3ea", marginTop: 6 }}>
                        labels: {record.labels.join(", ")}
                      </div>
                    )}
                    <pre style={{ whiteSpace: "pre-wrap", color: "#dce7f5", marginBottom: 0 }}>
                      {JSON.stringify(record.actual_resolution, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {audit.slice(0, 8).map((event) => (
                <div key={event.id} style={{ color: "#bfd3ea" }}>
                  <strong>{event.event_type}</strong> · {new Date(event.created_at).toLocaleString()}
                </div>
              ))}
            </div>
          </section>
        </section>
      </div>

      {detail.relation_evidence && (
        <section style={cardStyle}>
          <h3 style={{ marginTop: 0 }}>Relation Evidence</h3>
          {storedRelation && (
            <div style={{ color: "#bfd3ea", marginBottom: 10 }}>
              persisted {storedRelation.relation_type} @ {(storedRelation.confidence * 100).toFixed(1)}% · live{" "}
              {detail.relation_evidence.relation_type} @ {(detail.relation_evidence.confidence * 100).toFixed(1)}%
            </div>
          )}
          <div style={{ display: "grid", gap: 10 }}>
            <div style={{ color: "#9fb4ca" }}>
              {detail.relation_evidence.from_market_id} → {detail.relation_evidence.to_market_id}
              {" · "}
              {detail.relation_evidence.relation_type}
              {" · "}
              confidence {(detail.relation_evidence.confidence * 100).toFixed(1)}%
            </div>
            <div style={{ color: "#bfd3ea" }}>
              created by {detail.relation_evidence.created_by}
              {detail.relation_evidence.semantic_confidence != null
                ? ` · semantic ${(detail.relation_evidence.semantic_confidence * 100).toFixed(1)}%`
                : ""}
              {" · "}
              evidence {detail.relation_evidence.evidence_version}
            </div>
            <div style={{ color: "#bfd3ea" }}>
              oracle {detail.relation_evidence.oracle_alignment ?? "n/a"} · deadline{" "}
              {detail.relation_evidence.deadline_alignment ?? "n/a"} · source{" "}
              {detail.relation_evidence.source_alignment ?? "n/a"}
            </div>
            {detail.relation_evidence.ambiguity_terms.length > 0 && (
              <div style={{ color: "#bfd3ea" }}>
                ambiguity terms: {detail.relation_evidence.ambiguity_terms.join(", ")}
              </div>
            )}
            {detail.relation_evidence.semantic_reasoning && (
              <p style={{ margin: 0, color: "#dce7f5" }}>{detail.relation_evidence.semantic_reasoning}</p>
            )}
            {detail.relation_evidence.comparison_axes.length > 0 && (
              <div style={{ color: "#bfd3ea" }}>
                comparison axes: {detail.relation_evidence.comparison_axes.join(", ")}
              </div>
            )}
            {detail.relation_evidence.identity_provenance && (
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "#dce7f5" }}>
                {JSON.stringify(detail.relation_evidence.identity_provenance, null, 2)}
              </pre>
            )}
            {Object.keys(detail.relation_evidence.relation_signals).length > 0 && (
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "#dce7f5" }}>
                {JSON.stringify(detail.relation_evidence.relation_signals, null, 2)}
              </pre>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 4, letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ color: "#ecf4ff", fontWeight: 700 }}>{value}</div>
    </div>
  );
}
