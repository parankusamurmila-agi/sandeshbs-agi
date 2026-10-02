import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { generateDraft, getCorrespondence, updateDraft } from "../api/client";
import AuditTrail from "../components/AuditTrail";
import DraftEditor from "../components/DraftEditor";
import EvidencePanel from "../components/EvidencePanel";
import RequestList from "../components/RequestList";
import type { Correspondence } from "../types";

const ACTOR = "demo-user";

export default function CorrespondenceDetail() {
  const { id } = useParams<{ id: string }>();
  const [correspondence, setCorrespondence] = useState<Correspondence | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getCorrespondence(id).then((c) => {
      setCorrespondence(c);
      setSelectedId(c.requests[0]?.request_id ?? null);
    });
  }, [id]);

  const selectedRequest = correspondence?.requests.find((r) => r.request_id === selectedId) ?? null;

  function patchRequest(updated: typeof selectedRequest) {
    if (!updated || !correspondence) return;
    setCorrespondence({
      ...correspondence,
      requests: correspondence.requests.map((r) => (r.request_id === updated.request_id ? updated : r)),
    });
  }

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  if (!correspondence) return <p>Loading…</p>;

  return (
    <div>
      <h2>{correspondence.meta.product ?? correspondence.filename}</h2>
      <p style={{ color: "#555" }}>
        {correspondence.meta.applicant} · {correspondence.meta.source} · {correspondence.meta.letter_date}
      </p>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <div className="detail-layout">
        <div>
          <RequestList
            requests={correspondence.requests}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>

        {selectedRequest && (
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <h3>Request #{selectedRequest.request_id}</h3>
              <span style={{ fontSize: "0.8rem", color: "#777" }}>
                Source: page {selectedRequest.source.page}, paragraph {selectedRequest.source.paragraph}
              </span>
            </div>
            <p>{selectedRequest.text}</p>
            {selectedRequest.referenced_items.length > 0 && (
              <p style={{ fontSize: "0.85rem", color: "#555" }}>
                References: {selectedRequest.referenced_items.join(", ")}
              </p>
            )}

            <div className="section-title">Linked evidence</div>
            <EvidencePanel evidence={selectedRequest.linked_evidence} />

            <div className="section-title">Draft response</div>
            <DraftEditor
              request={selectedRequest}
              busy={busy}
              onGenerate={(direction) =>
                withBusy(async () => {
                  const updated = await generateDraft(correspondence.correspondence_id, selectedRequest.request_id, direction || null);
                  patchRequest(updated);
                })
              }
              onSave={(text) =>
                withBusy(async () => {
                  const updated = await updateDraft(correspondence.correspondence_id, selectedRequest.request_id, {
                    text,
                    actor: ACTOR,
                  });
                  patchRequest(updated);
                })
              }
              onApprove={(text) =>
                withBusy(async () => {
                  const updated = await updateDraft(correspondence.correspondence_id, selectedRequest.request_id, {
                    text,
                    action: "approve",
                    actor: ACTOR,
                  });
                  patchRequest(updated);
                })
              }
            />

            <div className="section-title">Audit trail</div>
            <AuditTrail audit={selectedRequest.audit} />
          </div>
        )}
      </div>
    </div>
  );
}
