import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCorrespondence } from "../api/client";
import Spinner from "../components/Spinner";
import type { CorrespondenceSummary } from "../types";

export default function CorrespondenceList() {
  const [items, setItems] = useState<CorrespondenceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    async function load() {
      try {
        const data = await listCorrespondence();
        if (cancelled) return;
        setItems(data);
        setError(null);
        // Keep refreshing while any upload is still extracting in the background.
        if (data.some((i) => i.status === "extracting")) {
          timer = window.setTimeout(load, 5000);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  if (loading) return <Spinner label="Loading correspondence…" />;
  if (error) return <p className="error-text">{error}</p>;

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
            {item.meta.applicant ?? "Unknown applicant"} ·{" "}
            {item.status === "extracting"
              ? "⏳ extracting…"
              : item.status === "failed"
                ? "⚠ extraction failed"
                : `${item.request_count} requests`}{" "}
            · {new Date(item.created_at).toLocaleString()}
          </div>
        </Link>
      ))}
    </div>
  );
}
