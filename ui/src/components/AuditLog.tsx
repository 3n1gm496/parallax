import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditEvent } from "../types";

export function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.audit
      .list(50)
      .then(setEvents)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading audit log…</p>;
  if (error) return <p style={{ color: "red" }}>Error: {error}</p>;
  if (events.length === 0) return <p>No audit events.</p>;

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85em" }}>
      <thead>
        <tr>
          <th>Time</th>
          <th>Type</th>
          <th>Entity</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e) => (
          <tr key={e.id}>
            <td>{new Date(e.created_at).toLocaleTimeString()}</td>
            <td>{e.event_type}</td>
            <td>{e.entity_id ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
