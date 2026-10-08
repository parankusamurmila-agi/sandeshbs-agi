import type { HaRequest } from "../types";
import StatusBadge from "./StatusBadge";

interface Props {
  requests: HaRequest[];
  selectedId: string | null;
  onSelect: (requestId: string) => void;
}

export default function RequestList({ requests, selectedId, onSelect }: Props) {
  return (
    <div>
      {requests.map((req) => (
        <div
          key={req.request_id}
          className={`request-list-item${req.request_id === selectedId ? " active" : ""}`}
          onClick={() => onSelect(req.request_id)}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <strong>#{req.request_id}</strong>
            <StatusBadge status={req.status} />
          </div>
          <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "#1a1a2e", marginTop: 2 }}>{req.drug}</div>
          <div style={{ fontSize: "0.8rem", color: "#555" }}>{req.section}</div>
          <div style={{ fontSize: "0.85rem", marginTop: 4 }}>
            {req.text.slice(0, 90)}
            {req.text.length > 90 ? "…" : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
