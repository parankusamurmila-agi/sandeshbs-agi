import { useEffect, useState } from "react";
import type { HaRequest } from "../types";
import Button from "./Button";

type PendingAction = "generate" | "save" | "approve" | null;

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
  // Which action is in flight, so the spinner shows only on the clicked button
  // (the parent shares one `busy` flag across link/generate/save/approve).
  const [pending, setPending] = useState<PendingAction>(null);

  useEffect(() => {
    setDraftText(request.draft?.text ?? "");
  }, [request.request_id, request.draft?.text]);

  useEffect(() => {
    if (!busy) setPending(null);
  }, [busy]);

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
        <Button
          loading={busy && pending === "generate"}
          onClick={() => {
            setPending("generate");
            onGenerate(direction);
          }}
          disabled={busy || !canGenerate || request.status === "approved"}
        >
          {busy && pending === "generate"
            ? "Generating…"
            : request.draft
              ? "Regenerate draft"
              : "Generate draft"}
        </Button>
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
            <Button
              className="secondary"
              loading={busy && pending === "save"}
              onClick={() => {
                setPending("save");
                onSave(draftText);
              }}
              disabled={busy || !isDirty || request.status === "approved"}
            >
              Save edit
            </Button>
            <Button
              loading={busy && pending === "approve"}
              onClick={() => {
                setPending("approve");
                onApprove(draftText);
              }}
              disabled={busy || request.status === "approved"}
            >
              {request.status === "approved" ? "Approved" : "Approve"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
