import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import type { AuditEvent } from "../types";

const panelStyle: CSSProperties = {
  border: "1px solid rgba(148, 163, 184, 0.18)",
  borderRadius: 18,
  background: "rgba(15, 23, 42, 0.74)",
  padding: 18,
};

export function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.audit
      .list(75)
      .then(setEvents)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading audit log…</p>;
  if (error) return <p style={{ color: "#fca5a5" }}>Error: {error}</p>;
  if (events.length === 0) return <p>No audit events.</p>;

  return (
    <section style={panelStyle}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Audit Trail</h2>
        <p style={{ color: "#9fb4ca", marginBottom: 0 }}>
          Pipeline completions, candidate evaluations, position opens, and settlements in chronological order.
        </p>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {events.map((event) => (
          <div
            key={event.id}
            style={{
              borderRadius: 14,
              border: "1px solid rgba(148, 163, 184, 0.16)",
              background: "rgba(2, 6, 23, 0.35)",
              padding: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 8,
              }}
            >
              <strong>{event.event_type}</strong>
              <span style={{ color: "#9fb4ca" }}>{new Date(event.created_at).toLocaleString()}</span>
            </div>
            <div style={{ color: "#9fb4ca", marginBottom: 8 }}>
              entity {event.entity_id ?? "global"}
            </div>
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                color: "#dce7f5",
                fontFamily: "inherit",
              }}
            >
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </section>
  );
}
