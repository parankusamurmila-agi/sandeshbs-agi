import type { LinkedEvidence } from "../types";

export default function EvidencePanel({ evidence }: { evidence: LinkedEvidence[] }) {
  if (evidence.length === 0) {
    return <p style={{ color: "#777", fontSize: "0.85rem" }}>No evidence linked yet.</p>;
  }
  return (
    <div>
      {evidence.map((item) => (
        <div key={item.doc_id} className="evidence-item">
          <div style={{ fontWeight: 600 }}>
            {item.title} <span style={{ color: "#777", fontWeight: 400 }}>({item.doc_type})</span>
          </div>
          <div style={{ fontSize: "0.8rem", color: "#555" }}>{item.doc_id}</div>
          <div style={{ fontSize: "0.85rem", marginTop: 4 }}>{item.rationale}</div>
        </div>
      ))}
    </div>
  );
}
