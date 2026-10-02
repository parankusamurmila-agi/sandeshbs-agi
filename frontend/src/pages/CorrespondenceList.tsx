import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCorrespondence } from "../api/client";
import type { CorrespondenceSummary } from "../types";

export default function CorrespondenceList() {
  const [items, setItems] = useState<CorrespondenceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCorrespondence()
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading…</p>;
  if (error) return <p style={{ color: "crimson" }}>{error}</p>;

  if (items.length === 0) {
    return (
      <div className="card">
        <p>No correspondence uploaded yet.</p>
        <Link to="/upload">Upload the first one →</Link>
      </div>
    );
  }

  return (
    <div>
      <h2>Correspondence</h2>
      {items.map((item) => (
        <Link
          key={item.correspondence_id}
          to={`/correspondence/${item.correspondence_id}`}
          className="card"
          style={{ display: "block", marginBottom: 10, textDecoration: "none", color: "inherit" }}
        >
          <strong>{item.meta.product ?? item.filename}</strong>
          <div style={{ fontSize: "0.85rem", color: "#555" }}>
            {item.meta.applicant ?? "Unknown applicant"} · {item.request_count} requests ·{" "}
            {new Date(item.created_at).toLocaleString()}
          </div>
        </Link>
      ))}
    </div>
  );
}
