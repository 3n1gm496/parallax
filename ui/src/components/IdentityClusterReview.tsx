import { useEffect, useState, type CSSProperties } from "react";

import {
  fetchIdentityClusters,
  fetchIdentityMetrics,
  recomputeIdentityMetrics,
  type IdentityClusterEntry,
  type IdentityMetricsReport,
} from "../api/identity";

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

const metricCardStyle: CSSProperties = {
  borderRadius: 14,
  border: "1px solid rgba(148, 163, 184, 0.16)",
  background: "rgba(2, 6, 23, 0.35)",
  padding: 14,
};

const typeLabels: Record<string, string> = {
  same_event: "Same Event",
  duplicate_market: "Duplicate Market",
  near_duplicate: "Near Duplicate",
  subset: "Subset",
  superset: "Superset",
  same_event_diff_source: "Diff Source",
  same_event_diff_oracle: "Diff Oracle",
  same_event_diff_deadline: "Diff Deadline",
  correlated: "Correlated",
  false_equivalence: "False Equivalence",
};

function confidenceColor(confidence: number): string {
  if (confidence >= 0.85) return "#86efac";
  if (confidence >= 0.65) return "#fcd34d";
  return "#fca5a5";
}

function renderCluster(cluster: IdentityClusterEntry) {
  return (
    <div
      key={cluster.cluster_id}
      style={{
        borderTop: "1px solid rgba(148, 163, 184, 0.12)",
        paddingTop: 12,
        marginTop: 12,
        display: "grid",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ color: "#dce7f5", fontWeight: 600 }}>
            {cluster.primary_market_title ?? cluster.primary_market_id ?? cluster.cluster_key}
          </div>
          <div style={{ color: "#9fb4ca", fontSize: 12 }}>{cluster.cluster_key}</div>
        </div>
        <div style={{ color: confidenceColor(cluster.confidence), fontWeight: 700 }}>
          {(cluster.confidence * 100).toFixed(0)}%
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", color: "#bfd3ea", fontSize: 13 }}>
        <span>{typeLabels[cluster.identity_type] ?? cluster.identity_type}</span>
        <span>{cluster.member_count} members</span>
        <span>{cluster.status}</span>
      </div>
    </div>
  );
}

export function IdentityClusterReview() {
  const [clusters, setClusters] = useState<IdentityClusterEntry[]>([]);
  const [metrics, setMetrics] = useState<IdentityMetricsReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [recomputing, setRecomputing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [queue, report] = await Promise.all([fetchIdentityClusters(50), fetchIdentityMetrics()]);
      setClusters(queue.clusters);
      setMetrics(report);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const onRecompute = async () => {
    setRecomputing(true);
    try {
      await recomputeIdentityMetrics();
      await load();
    } finally {
      setRecomputing(false);
    }
  };

  return (
    <section style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Identity Cluster Review</h2>
          <p style={{ color: "#9fb4ca", marginBottom: 0 }}>
            Typed v3 clusters, benchmark snapshot, and operator review queue.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onRecompute()}
          disabled={recomputing}
          style={{
            borderRadius: 10,
            border: "1px solid rgba(96, 165, 250, 0.32)",
            background: recomputing ? "rgba(30, 41, 59, 0.6)" : "rgba(37, 99, 235, 0.22)",
            color: "#dbeafe",
            padding: "10px 14px",
            cursor: recomputing ? "default" : "pointer",
          }}
        >
          {recomputing ? "Recomputing..." : "Recompute Metrics"}
        </button>
      </div>

      {loading ? <p style={{ color: "#9fb4ca" }}>Loading identity clusters…</p> : null}
      {error ? <p style={{ color: "#fca5a5" }}>Error: {error}</p> : null}

      {metrics ? (
        <div
          style={{
            marginTop: 16,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 10,
          }}
        >
          <div style={metricCardStyle}>
            <div style={{ color: "#9fb4ca", fontSize: 12 }}>Clusters</div>
            <div style={{ color: "#dce7f5", fontSize: 26, fontWeight: 700 }}>{metrics.cluster_count}</div>
          </div>
          <div style={metricCardStyle}>
            <div style={{ color: "#9fb4ca", fontSize: 12 }}>Verified</div>
            <div style={{ color: "#86efac", fontSize: 26, fontWeight: 700 }}>{metrics.verified_count}</div>
          </div>
          <div style={metricCardStyle}>
            <div style={{ color: "#9fb4ca", fontSize: 12 }}>Ambiguous</div>
            <div style={{ color: "#fcd34d", fontSize: 26, fontWeight: 700 }}>{metrics.ambiguous_count}</div>
          </div>
          <div style={metricCardStyle}>
            <div style={{ color: "#9fb4ca", fontSize: 12 }}>Benchmark</div>
            <div style={{ color: "#dce7f5", fontSize: 26, fontWeight: 700 }}>
              {metrics.benchmark_accuracy == null ? "n/a" : `${(metrics.benchmark_accuracy * 100).toFixed(1)}%`}
            </div>
          </div>
        </div>
      ) : null}

      {!loading && !error ? (
        <div style={{ marginTop: 16 }}>
          {clusters.length === 0 ? <p style={{ color: "#9fb4ca" }}>No active identity clusters found.</p> : clusters.map(renderCluster)}
        </div>
      ) : null}
    </section>
  );
}
