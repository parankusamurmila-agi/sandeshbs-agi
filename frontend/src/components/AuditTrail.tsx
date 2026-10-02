import type { AuditEntry } from "../types";

export default function AuditTrail({ audit }: { audit: AuditEntry[] }) {
  if (audit.length === 0) {
    return <p style={{ color: "#777", fontSize: "0.85rem" }}>No activity yet.</p>;
  }
  return (
    <div>
      {audit.map((entry, i) => (
        <div key={i} className="audit-item">
          <strong>{entry.action}</strong> by {entry.actor} — {new Date(entry.ts).toLocaleString()}
          {entry.note ? ` (${entry.note})` : ""}
        </div>
      ))}
    </div>
  );
}
