export type RequestStatus = "extracted" | "drafted" | "approved";

export interface SourceLocation {
  page: number;
  paragraph: number;
}

export interface LinkedEvidence {
  doc_id: string;
  title: string;
  doc_type: string;
  rationale: string;
}

export interface Draft {
  text: string;
  citations: string[];
}

export interface AuditEntry {
  action: "drafted" | "edited" | "approved";
  actor: string;
  ts: string;
  note?: string | null;
}

export interface HaRequest {
  request_id: string;
  section: string;
  text: string;
  referenced_items: string[];
  source: SourceLocation;
  status: RequestStatus;
  linked_evidence: LinkedEvidence[];
  direction?: string | null;
  draft?: Draft | null;
  audit: AuditEntry[];
}

export interface CorrespondenceMeta {
  applicant?: string | null;
  product?: string | null;
  letter_date?: string | null;
  source?: string | null;
}

export interface Correspondence {
  correspondence_id: string;
  s3_key: string;
  filename: string;
  meta: CorrespondenceMeta;
  status: string;
  requests: HaRequest[];
  created_at: string;
}

export interface CorrespondenceSummary {
  correspondence_id: string;
  filename: string;
  meta: CorrespondenceMeta;
  request_count: number;
  created_at: string;
}
