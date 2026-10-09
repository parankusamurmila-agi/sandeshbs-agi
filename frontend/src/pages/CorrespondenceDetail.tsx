import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { generateDraft, getCorrespondence, linkRegistration, updateDraft } from "../api/client";
import AuditTrail from "../components/AuditTrail";
import DraftEditor from "../components/DraftEditor";
import EvidencePanel from "../components/EvidencePanel";
import InvocationsPanel from "../components/InvocationsPanel";
import PdfSourceViewer from "../components/PdfSourceViewer";
import RequestList from "../components/RequestList";
import Spinner from "../components/Spinner";
import type { Correspondence } from "../types";

const ACTOR = "demo-user";

type Tab = "requests" | "audit";

export default function CorrespondenceDetail() {
  const { id } = useParams<{ id: string }>();
  const [correspondence, setCorrespondence] = useState<Correspondence | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("requests");
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: number | undefined;

    async function load() {
      const c = await getCorrespondence(id!);
      if (cancelled) return;
      setCorrespondence(c);
      setSelectedId((prev) => prev ?? c.requests[0]?.request_id ?? null);
      // Extraction runs asynchronously on the backend; poll until it finishes.
      if (c.status === "extracting") {
        timer = window.setTimeout(load, 4000);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [id]);

  // Don't leak "show source" across questions -- reset whenever the
  // selected question changes.
  useEffect(() => {
    setShowSource(false);
  }, [selectedId]);

  const selectedRequest = correspondence?.requests.find((r) => r.request_id === selectedId) ?? null;

  async function refresh() {
    if (!correspondence) return;
    const fresh = await getCorrespondence(correspondence.correspondence_id);
    setCorrespondence(fresh);
  }

  // Busy state is tracked per-question (not page-wide), so generating a
  // draft for one question never disables Link/Generate for another --
  // both run as independent, concurrent HTTP calls against the backend.
  async function withBusy(requestId: string, fn: () => Promise<void>) {
    setBusyIds((prev) => new Set(prev).add(requestId));
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev);
        next.delete(requestId);
        return next;
      });
    }
  }

  if (!correspondence) return <Spinner label="Loading correspondence…" />;

  const drugCount = new Set(correspondence.requests.map((r) => r.drug)).size;
  const busy = selectedRequest ? busyIds.has(selectedRequest.request_id) : false;

  return (
    <div>
      <h2>{correspondence.meta.product ?? correspondence.filename}</h2>
      <p style={{ color: "#555" }}>
        {correspondence.meta.applicant} · {correspondence.meta.source} · {correspondence.meta.letter_date}
      </p>
      <p style={{ color: "#555", fontSize: "0.85rem" }}>
        {correspondence.requests.length} question{correspondence.requests.length === 1 ? "" : "s"} · {drugCount} drug
        {drugCount === 1 ? "" : "s"} identified
      </p>
      {error && <p className="error-text">{error}</p>}

      {correspondence.status === "extracting" && (
        <div className="card" style={{ background: "#f5f3ff", border: "1px solid #ddd6fe" }}>
          <p style={{ margin: 0 }}>
            ⏳ Extracting questions from the letter… This page updates automatically.
          </p>
        </div>
      )}
      {correspondence.status === "failed" && (
        <p className="error-text">Extraction failed — see the Audit tab for details, or try re-uploading.</p>
      )}

      <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
        <button className={tab === "requests" ? "" : "secondary"} onClick={() => setTab("requests")}>
          Requests
        </button>
        <button className={tab === "audit" ? "" : "secondary"} onClick={() => setTab("audit")}>
          Audit
        </button>
      </div>

      {tab === "requests" && (
        <div className="detail-layout">
          <div>
            <RequestList
              requests={correspondence.requests}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>

          {selectedRequest && (
            <div className="card request-detail">
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <h3>
                  #{selectedRequest.request_id} · {selectedRequest.drug}
                </h3>
                <span style={{ fontSize: "0.8rem", color: "#777" }}>
                  Source: page {selectedRequest.source.page} — "{selectedRequest.source.quote}"
                </span>
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem", marginTop: 4 }}>
                <input type="checkbox" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} />
                Show source in PDF
              </label>
              {showSource && (
                <PdfSourceViewer
                  correspondenceId={correspondence.correspondence_id}
                  page={selectedRequest.source.page}
                  quote={selectedRequest.source.quote}
                />
              )}
              <p>{selectedRequest.text}</p>
              {selectedRequest.referenced_items.length > 0 && (
                <p style={{ fontSize: "0.85rem", color: "#555" }}>
                  References: {selectedRequest.referenced_items.join(", ")}
                </p>
              )}

              <div className="section-title">Linked evidence</div>
              <EvidencePanel
                request={selectedRequest}
                busy={busy}
                onLink={() =>
                  withBusy(selectedRequest.request_id, async () => {
                    await linkRegistration(correspondence.correspondence_id, selectedRequest.request_id);
                    await refresh();
                  })
                }
              />

              <div className="section-title">Draft response</div>
              <DraftEditor
                request={selectedRequest}
                busy={busy}
                onGenerate={(direction) =>
                  withBusy(selectedRequest.request_id, async () => {
                    await generateDraft(correspondence.correspondence_id, selectedRequest.request_id, direction || null);
                    await refresh();
                  })
                }
                onSave={(text) =>
                  withBusy(selectedRequest.request_id, async () => {
                    await updateDraft(correspondence.correspondence_id, selectedRequest.request_id, {
                      text,
                      actor: ACTOR,
                    });
                    await refresh();
                  })
                }
                onApprove={(text) =>
                  withBusy(selectedRequest.request_id, async () => {
                    await updateDraft(correspondence.correspondence_id, selectedRequest.request_id, {
                      text,
                      action: "approve",
                      actor: ACTOR,
                    });
                    await refresh();
                  })
                }
              />
            </div>
          )}
        </div>
      )}

      {tab === "audit" && (
        <div className="card">
          <div className="section-title">Document audit trail</div>
          <AuditTrail audit={correspondence.audit} />

          <div className="section-title">LLM invocations (tokens &amp; estimated cost)</div>
          <InvocationsPanel
            invocations={correspondence.invocations}
            onSelectRequest={(requestId) => {
              setSelectedId(requestId);
              setTab("requests");
            }}
          />
        </div>
      )}
    </div>
  );
}
