import type { HaRequest } from "../types";

interface Props {
  request: HaRequest;
  busy: boolean;
  onLink: () => void;
}

export default function EvidencePanel({ request, busy, onLink }: Props) {
  const { linked_registration, linked_submissions, linked_precedents, status, drug } = request;
  const hasAnyEvidence = linked_registration.length > 0 || linked_submissions.length > 0 || linked_precedents.length > 0;

  if (!hasAnyEvidence) {
    return (
      <div>
        <p style={{ color: "#777", fontSize: "0.85rem" }}>
          {status === "extracted"
            ? `No evidence linked yet for "${drug}".`
            : `No registration record matched for "${drug}" (so no submission content or precedent either).`}
        </p>
        {status !== "approved" && (
          <button onClick={onLink} disabled={busy}>
            Link registration record
          </button>
        )}
      </div>
    );
  }

  return (
    <div>
      {linked_registration.length > 0 && (
        <>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>
            Registration record
          </div>
          {linked_registration.map((reg) => (
            <div key={reg.registration_id} className="evidence-item">
              <div style={{ fontWeight: 600 }}>
                {reg.product}{" "}
                <span style={{ color: "#777", fontWeight: 400 }}>
                  ({reg.health_authority} · {reg.market})
                </span>
              </div>
              <div style={{ fontSize: "0.8rem", color: "#555" }}>
                {reg.registration_id} · {reg.application_number} ({reg.application_type}) · {reg.status}
              </div>
              <div style={{ fontSize: "0.85rem", marginTop: 4 }}>
                Last HA correspondence: {reg.last_ha_correspondence?.type ?? "n/a"} on{" "}
                {reg.last_ha_correspondence?.date ?? "n/a"}
                {reg.response_due_date ? ` · Response due ${reg.response_due_date}` : ""}
              </div>
            </div>
          ))}
        </>
      )}

      {linked_submissions.length > 0 && (
        <>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#666", textTransform: "uppercase", marginTop: 12, marginBottom: 4 }}>
            Submission content
          </div>
          {linked_submissions.map((sub) => (
            <div key={sub.doc_id} className="evidence-item">
              <div style={{ fontWeight: 600 }}>
                {sub.title} <span style={{ color: "#777", fontWeight: 400 }}>({sub.doc_type})</span>
              </div>
              <div style={{ fontSize: "0.8rem", color: "#555" }}>
                {sub.doc_id}
                {sub.module ? ` · ${sub.module}` : ""}
              </div>
              <div style={{ fontSize: "0.85rem", marginTop: 4 }}>{sub.summary}</div>
            </div>
          ))}
        </>
      )}

      {linked_precedents.length > 0 && (
        <>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#666", textTransform: "uppercase", marginTop: 12, marginBottom: 4 }}>
            Historic precedent
          </div>
          {linked_precedents.map((prec) => (
            <div key={prec.precedent_id} className="evidence-item">
              <div style={{ fontWeight: 600 }}>{prec.precedent_id}</div>
              <div style={{ fontSize: "0.85rem", marginTop: 4 }}>
                <strong>Prior deficiency:</strong> {prec.prior_deficiency}
              </div>
              <div style={{ fontSize: "0.85rem", marginTop: 4 }}>
                <strong>Prior response:</strong> {prec.prior_response_summary}
              </div>
              <div style={{ fontSize: "0.8rem", color: "#555", marginTop: 4 }}>Outcome: {prec.outcome}</div>
            </div>
          ))}
        </>
      )}

      {status !== "approved" && (
        <button className="secondary" onClick={onLink} disabled={busy} style={{ marginTop: 12 }}>
          Re-link registration record
        </button>
      )}
    </div>
  );
}
