import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import { IdentityClusterReview } from "./IdentityClusterReview";
import type {
  BacktestReplayReport,
  CalibrationStatusResponse,
  CandidateFunnelReport,
  EvaluationReport,
  ExecutionReport,
  IdentityClusterQueueResponse,
  IdentityReviewQueueResponse,
  LogicalRelationSet,
  OpsMetrics,
  PolicyReport,
  ReadinessReport,
  RunProof,
  SensitivityReport,
  ShadowCandidateListResponse,
} from "../types";

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

const statCardStyle: CSSProperties = {
  borderRadius: 16,
  border: "1px solid rgba(148, 163, 184, 0.16)",
  background: "rgba(2, 6, 23, 0.35)",
  padding: 16,
};

function formatWhen(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "n/a";
}

function formatMetric(value: number | null | undefined, digits = 4): string {
  if (value == null || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

function renderCounts(entries: Record<string, number>) {
  const rows = Object.entries(entries).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return <span style={{ color: "#9fb4ca" }}>No data.</span>;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {rows.map(([label, count]) => (
        <div
          key={label}
          style={{ display: "flex", justifyContent: "space-between", gap: 12, color: "#dce7f5" }}
        >
          <span style={{ color: "#9fb4ca" }}>{label}</span>
          <strong>{count}</strong>
        </div>
      ))}
    </div>
  );
}

function renderReasonRows(rows: Array<{ reason: string; count: number }>) {
  if (rows.length === 0) return <span style={{ color: "#9fb4ca" }}>No blockers recorded.</span>;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {rows.map((row) => (
        <div
          key={row.reason}
          style={{ display: "flex", justifyContent: "space-between", gap: 12, color: "#dce7f5" }}
        >
          <span style={{ color: "#9fb4ca" }}>{row.reason}</span>
          <strong>{row.count}</strong>
        </div>
      ))}
    </div>
  );
}

function formatCountPct(label: string, value: { count: number; pct: number | null }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, color: "#dce7f5" }}>
      <span style={{ color: "#9fb4ca" }}>{label}</span>
      <strong>
        {value.count}
        {value.pct != null ? ` (${value.pct.toFixed(1)}%)` : ""}
      </strong>
    </div>
  );
}

export function OperationsView() {
  const [metrics, setMetrics] = useState<OpsMetrics | null>(null);
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [runProofs, setRunProofs] = useState<RunProof[]>([]);
  const [relationSets, setRelationSets] = useState<LogicalRelationSet[]>([]);
  const [evaluation, setEvaluation] = useState<EvaluationReport | null>(null);
  const [policy, setPolicy] = useState<PolicyReport | null>(null);
  const [identityReview, setIdentityReview] = useState<IdentityReviewQueueResponse | null>(null);
  const [backtest, setBacktest] = useState<BacktestReplayReport | null>(null);
  const [execReport, setExecReport] = useState<ExecutionReport | null>(null);
  const [calibration, setCalibration] = useState<CalibrationStatusResponse | null>(null);
  const [identityClusters, setIdentityClusters] = useState<IdentityClusterQueueResponse | null>(null);
  const [candidateFunnel, setCandidateFunnel] = useState<CandidateFunnelReport | null>(null);
  const [shadowCandidates, setShadowCandidates] = useState<ShadowCandidateListResponse | null>(null);
  const [sensitivity, setSensitivity] = useState<SensitivityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.ops.metrics(),
      api.runtime.ready(),
      api.ops.runs(),
      api.ops.evaluation(),
      api.ops.relationSets(),
      api.ops.policy(),
      api.ops.identityReview(),
      api.ops.identityClusters(),
      api.ops.backtest(),
      api.ops.execution(),
      api.ops.calibration(),
      api.ops.candidateFunnel(),
      api.ops.shadowCandidates(),
      api.ops.sensitivity(),
    ]).then(([metricsPayload, readinessPayload, runsPayload, evaluationPayload, relationSetPayload, policyPayload, identityReviewPayload, identityClustersPayload, backtestPayload, execPayload, calibrationPayload, funnelPayload, shadowPayload, sensitivityPayload]) => {
        if (!cancelled) {
          setMetrics(metricsPayload);
          setReadiness(readinessPayload);
          setRunProofs(runsPayload.runs);
          setEvaluation(evaluationPayload);
          setRelationSets(relationSetPayload.items);
          setPolicy(policyPayload);
          setIdentityReview(identityReviewPayload);
          setIdentityClusters(identityClustersPayload);
          setBacktest(backtestPayload);
          setExecReport(execPayload);
          setCalibration(calibrationPayload);
          setCandidateFunnel(funnelPayload);
          setShadowCandidates(shadowPayload);
          setSensitivity(sensitivityPayload);
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

  if (loading) return <p>Loading operations…</p>;
  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;
  if (!metrics) return <p style={{ color: "#9fb4ca" }}>No operational metrics available.</p>;

  const pipelineActivities = Object.entries(metrics.pipeline.activity_metrics);
  const evaluationMetrics = evaluation?.metrics ?? metrics.evaluation;

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
          ["Runtime status", readiness?.status ?? "n/a"],
          ["Open positions", metrics.open_positions],
          ["Audit events 24h", metrics.audit.events_last_24h],
          ["Candidate evals 24h", metrics.pipeline.candidate_evaluations_last_24h],
          ["Settlements 24h", metrics.pipeline.settlements_last_24h],
          ["Verified clusters", identityClusters?.clusters.filter((row) => row.confidence >= 0.75).length ?? 0],
        ].map(([label, value]) => (
          <div key={String(label)} style={statCardStyle}>
            <div style={{ color: "#9fb4ca", fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              {label}
            </div>
            <div style={{ fontSize: 30, marginTop: 10, fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </section>

      {candidateFunnel && shadowCandidates && sensitivity && (
        <section style={{ display: "grid", gap: 16 }}>
          <section
            style={{
              ...panelStyle,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: 14,
            }}
          >
            <div style={statCardStyle}>
              <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Candidate Funnel</div>
              <div style={{ color: "#dce7f5", marginTop: 10, display: "grid", gap: 8 }}>
                <div><strong>Run</strong> {candidateFunnel.run_id}</div>
                {formatCountPct("Compiled", candidateFunnel.compilation.compiled)}
                {formatCountPct("Verified identity", candidateFunnel.identity.verified)}
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Tradeable relations</span>
                  <strong>{candidateFunnel.relations.tradeable_true}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Persisted candidates</span>
                  <strong>{candidateFunnel.persistence.persisted_candidates}</strong>
                </div>
              </div>
            </div>

            <div style={statCardStyle}>
              <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Top Blockers</div>
              <div style={{ marginTop: 10 }}>{renderReasonRows(candidateFunnel.top_blockers)}</div>
            </div>

            <div style={statCardStyle}>
              <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Solver Diagnostics</div>
              <div style={{ color: "#dce7f5", marginTop: 10, display: "grid", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Solver called</span>
                  <strong>{candidateFunnel.solver.solver_called}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Solver not called</span>
                  <strong>{candidateFunnel.solver.solver_not_called}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Returned none</span>
                  <strong>{candidateFunnel.solver.returned_none}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Threshold rejects</span>
                  <strong>{candidateFunnel.solver.threshold_rejects}</strong>
                </div>
              </div>
            </div>

            <div style={statCardStyle}>
              <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Preview</div>
              <div style={{ color: "#dce7f5", marginTop: 10, display: "grid", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Positive displayed edge</span>
                  <strong>{candidateFunnel.preview.positive_displayed_edge}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Positive executable edge</span>
                  <strong>{candidateFunnel.preview.positive_executable_edge}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#9fb4ca" }}>Only identity blocked</span>
                  <strong>{candidateFunnel.preview.failed_only_identity_unverified}</strong>
                </div>
              </div>
            </div>
          </section>

          <section
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)",
              gap: 16,
            }}
          >
            <div style={panelStyle}>
              <h2 style={{ marginTop: 0, fontSize: 18 }}>Shadow Candidates</h2>
              <div style={{ color: "#9fb4ca", marginBottom: 12 }}>
                Top {Math.min(20, shadowCandidates.rows.length)} near-misses from run {shadowCandidates.run_id}
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                {shadowCandidates.rows.slice(0, 20).map((row) => (
                  <div key={row.observation_id} style={statCardStyle}>
                    <div style={{ color: "#dce7f5" }}>
                      <strong>{row.relation_type}</strong> · {row.market_ids.join(" | ")}
                    </div>
                    <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                      blockers {row.blocking_gates.join(", ") || "none"} · minimal relaxation {row.minimal_relaxation.join(", ") || "none"}
                    </div>
                    <div style={{ color: "#bfd3ea", marginTop: 6 }}>
                      displayed {formatMetric(row.displayed_edge)} · executable {formatMetric(row.executable_edge)} · dangerous {String(row.dangerous_relaxation)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: "grid", gap: 16 }}>
              <section style={panelStyle}>
                <h2 style={{ marginTop: 0, fontSize: 18 }}>Sensitivity</h2>
                <div style={{ color: "#9fb4ca", marginBottom: 12 }}>Diagnostic only. No production recommendation is applied automatically.</div>
                <div style={{ display: "grid", gap: 14 }}>
                  <div>
                    <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Threshold table</div>
                    {renderCounts(Object.fromEntries(sensitivity.min_profit_thresholds.map((row) => [row.label, row.count])))}
                  </div>
                  <div>
                    <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Identity gate table</div>
                    {renderCounts(Object.fromEntries(sensitivity.identity_gates.map((row) => [row.label, row.count])))}
                  </div>
                  <div>
                    <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Semantic gate table</div>
                    {renderCounts(Object.fromEntries(sensitivity.semantic_thresholds.map((row) => [row.label, row.count])))}
                  </div>
                  <div>
                    <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Execution gate table</div>
                    {renderCounts(Object.fromEntries(sensitivity.execution_modes.map((row) => [row.label, row.count])))}
                  </div>
                </div>
              </section>
            </div>
          </section>
        </section>
      )}

      <IdentityClusterReview />

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.4fr) minmax(320px, 0.9fr)",
          gap: 16,
        }}
      >
        <div style={panelStyle}>
          <div style={{ marginBottom: 14 }}>
            <h2 style={{ margin: 0, fontSize: 18 }}>Pipeline Activity</h2>
            <p style={{ color: "#9fb4ca", marginBottom: 0 }}>
              Persisted run proofs are primary. Audit stage events remain visible as supporting telemetry.
            </p>
          </div>
          <div style={{ display: "grid", gap: 12 }}>
            {runProofs.length > 0 && (
              <div style={statCardStyle}>
                <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 10, letterSpacing: "0.08em" }}>
                  PERSISTED RUN PROOFS
                </div>
                <div style={{ display: "grid", gap: 10 }}>
                  {runProofs.map((run, index) => (
                    <div
                      key={`${run.run_id}-${run.config_fingerprint}-${index}`}
                      style={{ color: "#dce7f5" }}
                    >
                      <strong>{run.run_id}</strong>
                      <div style={{ color: "#9fb4ca", marginTop: 4 }}>
                        {run.run_status} · fingerprint {run.config_fingerprint} · markets {run.markets_ingested} · relations{" "}
                        {run.relations_detected} · candidates {run.candidates_found} · positions {run.positions_opened}
                      </div>
                      <div style={{ color: "#bfd3ea", marginTop: 4 }}>
                        platforms {Object.entries(run.market_counts_by_platform)
                          .map(([platform, count]) => `${platform}:${count}`)
                          .join(" · ") || "n/a"}
                      </div>
                      <div style={{ color: "#9fb4ca", marginTop: 4 }}>
                        started {formatWhen(run.started_at)} · completed {formatWhen(run.completed_at)}
                      </div>
                      {(run.non_fatal_errors.length > 0 || run.fatal_errors.length > 0) && (
                        <div style={{ color: "#fca5a5", marginTop: 4 }}>
                          errors: {[...run.fatal_errors, ...run.non_fatal_errors].join(" | ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {pipelineActivities.map(([activity, metric]) => (
              <div key={activity} style={statCardStyle}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                    marginBottom: 8,
                  }}
                >
                  <strong>{activity}</strong>
                  <span style={{ color: "#9fb4ca" }}>{metric.runs} runs</span>
                </div>
                <div style={{ color: "#9fb4ca", marginBottom: 10 }}>
                  Latest activity {formatWhen(metric.latest_at)}
                </div>
                <pre
                  style={{
                    margin: 0,
                    whiteSpace: "pre-wrap",
                    color: "#dce7f5",
                    fontFamily: "inherit",
                    fontSize: 13,
                  }}
                >
                  {JSON.stringify(metric.latest_payload, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Readiness</h2>
            {readiness ? (
              <div style={{ display: "grid", gap: 14 }}>
                <div style={{ color: "#9fb4ca" }}>
                  Database {readiness.database} · overall status {readiness.status}
                </div>
                {readiness.degraded_reasons.length > 0 && (
                  <div style={{ color: "#fca5a5" }}>
                    reasons: {readiness.degraded_reasons.join(" | ")}
                  </div>
                )}
                <div style={{ color: "#dce7f5" }}>
                  <strong>Controls</strong>: global pause {String(readiness.controls.global_pause)} · semantic analysis disabled{" "}
                  {String(readiness.controls.semantic_analysis_disabled)} · live execution enabled{" "}
                  {String(readiness.controls.live_execution_enabled)} · read-only{" "}
                  {String(readiness.controls.degraded_read_only_mode)}
                </div>
              <div style={{ color: "#dce7f5" }}>
                <strong>Semantic analysis</strong>: {readiness.checks.semantic_analysis.status} · provider{" "}
                {readiness.checks.semantic_analysis.provider} · min confidence{" "}
                {readiness.checks.semantic_analysis.min_relation_confidence ?? "n/a"}
                {readiness.checks.semantic_analysis.reason ? ` · ${readiness.checks.semantic_analysis.reason}` : ""}
              </div>
              {calibration?.active_policy && (
                <div style={{ color: "#dce7f5" }}>
                  <strong>Active policy</strong>: {calibration.active_policy.policy_version} · status {calibration.active_policy.status}
                </div>
              )}
                <div style={{ display: "grid", gap: 8 }}>
                  {Object.entries(readiness.checks.providers).map(([platform, check]) => (
                    <div key={platform} style={{ color: "#dce7f5" }}>
                      <strong>{platform}</strong>: {check.status} · provider {check.provider} · enabled{" "}
                      {String(check.enabled)} · configured {String(check.configured)} · markets {check.market_count ?? 0}
                      <div style={{ color: "#9fb4ca", marginTop: 4 }}>
                        latest {formatWhen(check.latest_market_at ?? null)}
                        {check.age_minutes != null ? ` · age ${check.age_minutes.toFixed(1)}m` : ""}
                        {check.reason ? ` · ${check.reason}` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p style={{ color: "#9fb4ca" }}>No readiness payload available.</p>
            )}
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Audit Shape</h2>
            <div style={{ color: "#9fb4ca", marginBottom: 14 }}>
              Total {metrics.audit.total_events} · latest {formatWhen(metrics.latest_audit_at)}
            </div>
            {renderCounts(metrics.audit.counts_by_event_type)}
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Autopsy Outcomes</h2>
            <div style={{ color: "#9fb4ca", marginBottom: 14 }}>
              Total {metrics.autopsy.total_records} · identity errors {metrics.autopsy.identity_errors} · latest{" "}
              {formatWhen(metrics.autopsy.latest_autopsy_at)}
            </div>
            <div style={{ display: "grid", gap: 14 }}>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Resolution types</div>
                {renderCounts(metrics.autopsy.counts_by_resolution_type)}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Autopsy labels</div>
                {renderCounts(metrics.autopsy.counts_by_label)}
              </div>
            </div>
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Calibration Pressure</h2>
            <div style={{ color: "#9fb4ca", marginBottom: 14 }}>
              policy {metrics.calibration.policy_version} · labeled autopsies {metrics.calibration.total_labeled_autopsies}
            </div>
            <div style={{ display: "grid", gap: 14 }}>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Label rates</div>
                {renderCounts(metrics.calibration.label_rate_by_type)}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Component pressure</div>
                {renderCounts(metrics.calibration.feedback_pressure_by_component)}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Recommended adjustments</div>
                {Object.keys(metrics.calibration.recommended_threshold_adjustments).length === 0 ? (
                  <span style={{ color: "#9fb4ca" }}>No adjustment pressure yet.</span>
                ) : (
                  <div style={{ display: "grid", gap: 8 }}>
                    {Object.entries(metrics.calibration.recommended_threshold_adjustments).map(([component, advice]) => (
                      <div key={component} style={{ color: "#dce7f5" }}>
                        <strong>{component}</strong>: {advice}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Evaluation Pack</h2>
            <div style={{ color: "#9fb4ca", marginBottom: 14 }}>
              policy {evaluationMetrics.policy_version} · settled positions {evaluationMetrics.settled_positions}
              {evaluation ? ` · generated ${formatWhen(evaluation.generated_at)}` : ""}
            </div>
            {evaluationMetrics.settled_positions === 0 ? (
              <p style={{ color: "#9fb4ca", marginBottom: 0 }}>
                No settled paper positions yet. This surface activates once settlement and autopsy data exist.
              </p>
            ) : (
              <div style={{ display: "grid", gap: 14 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                  <div style={statCardStyle}>
                    <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Win Rate</div>
                    <div style={{ fontSize: 24, marginTop: 8, fontWeight: 700 }}>
                      {formatMetric(evaluationMetrics.realized_win_rate)}
                    </div>
                  </div>
                  <div style={statCardStyle}>
                    <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>False Positive Rate</div>
                    <div style={{ fontSize: 24, marginTop: 8, fontWeight: 700 }}>
                      {formatMetric(evaluationMetrics.false_positive_rate)}
                    </div>
                  </div>
                  <div style={statCardStyle}>
                    <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Avg Expected Edge</div>
                    <div style={{ fontSize: 24, marginTop: 8, fontWeight: 700 }}>
                      {formatMetric(evaluationMetrics.average_expected_edge)}
                    </div>
                  </div>
                  <div style={statCardStyle}>
                    <div style={{ color: "#9fb4ca", fontSize: 12, textTransform: "uppercase" }}>Avg Realized PnL</div>
                    <div style={{ fontSize: 24, marginTop: 8, fontWeight: 700 }}>
                      {formatMetric(evaluationMetrics.average_realized_pnl)}
                    </div>
                  </div>
                </div>
                <div style={{ color: "#dce7f5" }}>
                  Edge capture ratio {formatMetric(evaluationMetrics.average_edge_capture_ratio)}
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Resolution mix</div>
                  {renderCounts(evaluationMetrics.resolution_mix)}
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Failure labels</div>
                  {renderCounts(evaluationMetrics.failure_labels)}
                </div>
                <div>
                  <div style={{ color: "#9fb4ca", marginBottom: 8 }}>By opportunity type</div>
                  <div style={{ display: "grid", gap: 10 }}>
                    {evaluationMetrics.opportunity_type_breakdown.map((item) => (
                      <div key={item.opportunity_type} style={statCardStyle}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                          <strong>{item.opportunity_type}</strong>
                          <span style={{ color: "#9fb4ca" }}>{item.settled_positions} settled</span>
                        </div>
                        <div style={{ color: "#bfd3ea", marginTop: 6 }}>
                          win rate {formatMetric(item.realized_win_rate)} · avg expected {formatMetric(item.average_expected_edge)} · avg realized{" "}
                          {formatMetric(item.average_realized_pnl)}
                        </div>
                        <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                          edge capture {formatMetric(item.average_edge_capture_ratio)}
                        </div>
                        {Object.keys(item.failure_labels).length > 0 && (
                          <div style={{ marginTop: 8 }}>{renderCounts(item.failure_labels)}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Relation Layer</h2>
            <div style={{ display: "grid", gap: 14 }}>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Verified pair relations</div>
                {renderCounts(metrics.relation_quality.verified_relation_counts_by_type)}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Verified relation sets</div>
                {renderCounts(metrics.relation_quality.verified_relation_set_counts_by_type)}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Recent n-ary relation sets</div>
                {relationSets.length === 0 ? (
                  <span style={{ color: "#9fb4ca" }}>No persisted relation sets.</span>
                ) : (
                  <div style={{ display: "grid", gap: 10 }}>
                    {relationSets.slice(0, 6).map((item) => (
                      <div key={item.relation_set_id ?? item.set_key} style={statCardStyle}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                          <strong>{item.relation_type}</strong>
                          <span style={{ color: "#9fb4ca" }}>
                            {item.proof_status} · tradeable {String(item.tradeable_relation)}
                          </span>
                        </div>
                        <div style={{ color: "#bfd3ea", marginTop: 6 }}>
                          members {item.member_market_ids.join(" · ") || "n/a"}
                        </div>
                        <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                          set key {item.set_key}
                        </div>
                        <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                          confidence {formatMetric(item.confidence)} · created by {item.created_by}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Proposals and vetoes</div>
                <div style={{ display: "grid", gap: 14 }}>
                  <div>
                    <div style={{ color: "#86a0b8", marginBottom: 6 }}>Proposal counts</div>
                    {renderCounts(metrics.relation_quality.proposal_counts_by_type)}
                  </div>
                  <div>
                    <div style={{ color: "#86a0b8", marginBottom: 6 }}>Logic rejections</div>
                    {renderCounts(metrics.relation_quality.logic_rejected_counts_by_type)}
                  </div>
                  <div>
                    <div style={{ color: "#86a0b8", marginBottom: 6 }}>Semantic veto counts</div>
                    {renderCounts(metrics.relation_quality.semantic_veto_counts_by_type)}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section style={panelStyle}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Runtime Inventory</h2>
            <div style={{ display: "grid", gap: 14 }}>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Markets by platform</div>
                {renderCounts(metrics.market_counts_by_platform)}
              </div>
              <div>
                <div style={{ color: "#9fb4ca", marginBottom: 8 }}>Candidates by decision</div>
                {renderCounts(metrics.candidate_counts_by_decision)}
              </div>
              <div style={{ color: "#9fb4ca", display: "grid", gap: 6 }}>
                <span>Latest ingest {formatWhen(metrics.latest_ingest_at)}</span>
                <span>Latest candidate {formatWhen(metrics.latest_candidate_at)}</span>
                <span>Latest pipeline event {formatWhen(metrics.pipeline.latest_pipeline_event_at)}</span>
              </div>
            </div>
          </section>
        </div>
      </section>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(320px, 0.9fr) minmax(0, 1.4fr)",
          gap: 16,
        }}
      >
        <div style={panelStyle}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Operator Workflow</h2>
          <p style={{ color: "#9fb4ca" }}>
            Action-oriented queue built from identity ambiguity, replay invalidations, and policy drift.
          </p>
          <div style={{ display: "grid", gap: 14 }}>
            <div style={statCardStyle}>
              <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 8, letterSpacing: "0.08em" }}>POLICY PRESSURE</div>
              {policy ? (
                <div style={{ display: "grid", gap: 8 }}>
                  <div style={{ color: "#dce7f5" }}>
                    policy {policy.policy_version} · calibration {policy.calibration_policy_version}
                  </div>
                  <div style={{ color: "#9fb4ca" }}>
                    identity {formatMetric(policy.identity_risk_pressure)} · semantic {formatMetric(policy.semantic_risk_pressure)} · execution{" "}
                    {formatMetric(policy.execution_risk_pressure)} · oracle {formatMetric(policy.oracle_risk_pressure)}
                  </div>
                  <div style={{ color: "#9fb4ca" }}>
                    review queue {policy.review_queue_size} · identity invalidations {policy.recent_identity_invalidations} · oracle invalidations{" "}
                    {policy.recent_oracle_invalidations}
                  </div>
                </div>
              ) : (
                <span style={{ color: "#9fb4ca" }}>No policy report.</span>
              )}
            </div>
            <div style={statCardStyle}>
              <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 8, letterSpacing: "0.08em" }}>IDENTITY REVIEW QUEUE</div>
              {!identityReview || identityReview.items.length === 0 ? (
                <span style={{ color: "#9fb4ca" }}>No queued identity reviews.</span>
              ) : (
                <div style={{ display: "grid", gap: 10 }}>
                  {identityReview.items.slice(0, 8).map((item) => (
                    <div key={item.candidate_id} style={{ color: "#dce7f5" }}>
                      <strong>{item.opportunity_type}</strong>
                      <div style={{ color: "#9fb4ca", marginTop: 4 }}>
                        candidate {item.candidate_id} · severity {item.ambiguity_severity} · venue risk {formatMetric(item.venue_mismatch_risk)}
                      </div>
                      <div style={{ color: "#bfd3ea", marginTop: 4 }}>{item.reasons.join(" | ")}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={panelStyle}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Recommended Actions</h2>
          {policy && policy.recommendations.length > 0 ? (
            <div style={{ display: "grid", gap: 10 }}>
              {policy.recommendations.map((recommendation) => (
                <div key={`${recommendation.component}-${recommendation.action}`} style={statCardStyle}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                    <strong>{recommendation.component}</strong>
                    <span style={{ color: recommendation.priority === "high" ? "#fca5a5" : "#fcd34d" }}>
                      {recommendation.priority}
                    </span>
                  </div>
                  <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                    pressure {formatMetric(recommendation.pressure)} · current {formatMetric(recommendation.current_value)} · suggested{" "}
                    {formatMetric(recommendation.recommended_value)}
                  </div>
                  <div style={{ color: "#dce7f5", marginTop: 6 }}>{recommendation.action}</div>
                  <div style={{ color: "#bfd3ea", marginTop: 6 }}>{recommendation.basis.join(" | ")}</div>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ color: "#9fb4ca" }}>No threshold changes currently recommended.</p>
          )}
          <div style={{ marginTop: 16 }}>
            <h3 style={{ marginBottom: 8, fontSize: 16 }}>Recent Invalidated Replays</h3>
            {!backtest || backtest.rows.length === 0 ? (
              <span style={{ color: "#9fb4ca" }}>No replay rows.</span>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {backtest.rows
                  .filter((row) => row.replay_outcome === "identity_invalidated" || row.replay_outcome === "oracle_invalidated")
                  .slice(0, 8)
                  .map((row) => (
                    <div key={`${row.candidate_id}-${row.snapshot_evaluated_at}`} style={statCardStyle}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                        <strong>{row.opportunity_type}</strong>
                        <span style={{ color: "#fca5a5" }}>{row.replay_outcome}</span>
                      </div>
                      <div style={{ color: "#9fb4ca", marginTop: 6 }}>
                        relation {row.relation_type_at_snapshot ?? "n/a"} · identity {row.identity_status_at_snapshot ?? "n/a"} · pnl{" "}
                        {formatMetric(row.actual_pnl)}
                      </div>
                      {row.autopsy_labels.length > 0 && (
                        <div style={{ color: "#bfd3ea", marginTop: 6 }}>labels: {row.autopsy_labels.join(", ")}</div>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {execReport && (
        <section style={panelStyle}>
          <h3 style={{ marginTop: 0 }}>Execution Coverage</h3>
          <div style={{ color: execReport.orderbook_enabled ? "#6ddc9b" : "#9fb4ca", marginBottom: 10 }}>
            orderbook {execReport.orderbook_enabled ? "enabled" : "disabled"} · {execReport.total_venue_tokens} tokens · {execReport.total_snapshots} snapshots
          </div>
          {execReport.coverage.map((c) => (
            <div key={c.platform} style={{ marginBottom: 6 }}>
              <span style={{ color: "#bfd3ea" }}>{c.platform}</span>
              {" — "}
              <span style={{ color: "#9fb4ca" }}>{c.venue_token_count} tokens · {c.snapshot_count} snapshots</span>
              {c.latest_snapshot_at && (
                <span style={{ color: "#6b829a", marginLeft: 8 }}>
                  last {new Date(c.latest_snapshot_at).toLocaleString()}
                </span>
              )}
            </div>
          ))}
          {Object.keys(execReport.execution_path_distribution).length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 6, letterSpacing: "0.08em" }}>EXECUTION PATH DISTRIBUTION</div>
              {Object.entries(execReport.execution_path_distribution).map(([path, count]) => (
                <div key={path} style={{ display: "flex", justifyContent: "space-between", color: "#9fb4ca", marginBottom: 4 }}>
                  <span>{path}</span>
                  <strong style={{ color: "#dce7f5" }}>{count}</strong>
                </div>
              ))}
            </div>
          )}
          {Object.keys(execReport.execution_model_distribution).length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: "#86a0b8", fontSize: 11, marginBottom: 6, letterSpacing: "0.08em" }}>LEGACY EXECUTION MODEL DISTRIBUTION</div>
              {Object.entries(execReport.execution_model_distribution).map(([model, count]) => (
                <div key={model} style={{ display: "flex", justifyContent: "space-between", color: "#9fb4ca", marginBottom: 4 }}>
                  <span>{model}</span>
                  <strong style={{ color: "#dce7f5" }}>{count}</strong>
                </div>
              ))}
            </div>
          )}
          {execReport.avg_quote_staleness_seconds !== null && (
            <div style={{ color: "#9fb4ca", marginTop: 8 }}>
              avg staleness {execReport.avg_quote_staleness_seconds.toFixed(1)}s
              {execReport.depth_support_rate !== null && ` · depth support ${(execReport.depth_support_rate * 100).toFixed(0)}%`}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
