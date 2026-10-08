import { useEffect, useState } from "react";
import type { HaRequest } from "../types";

interface Props {
  request: HaRequest;
  busy: boolean;
  onGenerate: (direction: string) => void;
  onSave: (text: string) => void;
  onApprove: (text: string) => void;
}

export default function DraftEditor({ request, busy, onGenerate, onSave, onApprove }: Props) {
  const [direction, setDirection] = useState(request.direction ?? "");
  const [draftText, setDraftText] = useState(request.draft?.text ?? "");

  useEffect(() => {
    setDraftText(request.draft?.text ?? "");
  }, [request.request_id, request.draft?.text]);

  const isDirty = draftText !== (request.draft?.text ?? "");
  const canGenerate = request.status !== "extracted";

  return (
    <div>
      <div className="section-title">Direction (optional)</div>
      <textarea
        rows={2}
        placeholder="e.g. Keep it concise; commit to a 30-day resubmission timeline."
        value={direction}
        onChange={(e) => setDirection(e.target.value)}
        disabled={busy || request.status === "approved"}
      />
      <div style={{ marginTop: 8 }}>
        <button
          onClick={() => onGenerate(direction)}
          disabled={busy || !canGenerate || request.status === "approved"}
        >
          {request.draft ? "Regenerate draft" : "Generate draft"}
        </button>
        {!canGenerate && (
          <p style={{ color: "#a15c00", fontSize: "0.8rem", marginTop: 4 }}>
            Link a registration record before generating a draft.
          </p>
        )}
      </div>

      {request.draft && (
        <>
          <div className="section-title">Draft response</div>
          {request.draft.template_id && (
            <div style={{ fontSize: "0.8rem", color: "#777", marginBottom: 4 }}>
              Template: {request.draft.template_id}
            </div>
          )}
          <textarea
            rows={10}
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
            disabled={busy || request.status === "approved"}
          />
          {request.draft.citations.length > 0 && (
            <div style={{ fontSize: "0.8rem", color: "#777", marginTop: 4 }}>
              Citations: {request.draft.citations.join(", ")}
            </div>
          )}
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button
              className="secondary"
              onClick={() => onSave(draftText)}
              disabled={busy || !isDirty || request.status === "approved"}
            >
              Save edit
            </button>
            <button onClick={() => onApprove(draftText)} disabled={busy || request.status === "approved"}>
              {request.status === "approved" ? "Approved" : "Approve"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
