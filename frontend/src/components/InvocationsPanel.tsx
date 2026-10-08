import type { Invocation } from "../types";

interface Props {
  invocations: Invocation[];
  onSelectRequest?: (requestId: string) => void;
}

function formatCost(usd: number): string {
  return `$${usd.toFixed(4)} (est.)`;
}

export default function InvocationsPanel({ invocations, onSelectRequest }: Props) {
  if (invocations.length === 0) {
    return <p style={{ color: "#777", fontSize: "0.85rem" }}>No LLM calls recorded yet.</p>;
  }

  const sorted = [...invocations].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  const totalCost = invocations.reduce((sum, inv) => sum + inv.estimated_cost_usd, 0);

  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #d8dce6" }}>
            <th style={{ padding: "6px 8px" }}>Kind</th>
            <th style={{ padding: "6px 8px" }}>Request</th>
            <th style={{ padding: "6px 8px" }}>Input tokens</th>
            <th style={{ padding: "6px 8px" }}>Output tokens</th>
            <th style={{ padding: "6px 8px" }}>Cache read</th>
            <th style={{ padding: "6px 8px" }}>Cache write</th>
            <th style={{ padding: "6px 8px" }}>Est. cost</th>
            <th style={{ padding: "6px 8px" }}>When</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((inv) => (
            <tr key={inv.invocation_id} style={{ borderBottom: "1px dashed #d8dce6" }}>
              <td style={{ padding: "6px 8px" }}>{inv.kind}</td>
              <td style={{ padding: "6px 8px" }}>
                {inv.request_id ? (
                  onSelectRequest ? (
                    <button className="secondary" onClick={() => onSelectRequest(inv.request_id!)} style={{ padding: "2px 8px" }}>
                      #{inv.request_id}
                    </button>
                  ) : (
                    `#${inv.request_id}`
                  )
                ) : (
                  "—"
                )}
              </td>
              <td style={{ padding: "6px 8px" }}>{inv.input_tokens}</td>
              <td style={{ padding: "6px 8px" }}>{inv.output_tokens}</td>
              <td style={{ padding: "6px 8px" }}>{inv.cache_read_input_tokens}</td>
              <td style={{ padding: "6px 8px" }}>{inv.cache_write_input_tokens}</td>
              <td style={{ padding: "6px 8px" }}>{formatCost(inv.estimated_cost_usd)}</td>
              <td style={{ padding: "6px 8px", color: "#777" }}>{new Date(inv.ts).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: "0.85rem", color: "#555", marginTop: 8 }}>
        Total estimated cost for this document: <strong>{formatCost(totalCost)}</strong>
      </p>
    </div>
  );
}
