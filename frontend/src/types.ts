export type RequestStatus = "extracted" | "linked" | "drafted" | "approved";

export interface SourceLocation {
  page: number;
  quote: string;
}

export interface RegistrationCorrespondence {
  type?: string | null;
  date?: string | null;
  reference?: string | null;
}

export interface RegistrationRecord {
  registration_id: string;
  product: string;
  application_number: string;
  application_type: string;
  health_authority: string;
  market: string;
  status: string;
  original_submission_date?: string | null;
  last_ha_correspondence?: RegistrationCorrespondence | null;
  response_due_date?: string | null;
  related_submission_doc_ids: string[];
}

export interface SubmissionDocument {
  doc_id: string;
  title: string;
  doc_type: string;
  module?: string | null;
  summary: string;
}

export interface HistoricPrecedent {
  precedent_id: string;
  prior_deficiency: string;
  prior_response_summary: string;
  outcome: string;
}

export interface Draft {
  text: string;
  citations: string[];
  template_id?: string | null;
}

export interface Invocation {
  invocation_id: string;
  kind: "extract" | "link" | "draft";
  request_id?: string | null;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_write_input_tokens: number;
  estimated_cost_usd: number;
  ts: string;
}

export interface AuditEntry {
  action: "uploaded" | "extracted" | "linked" | "drafted" | "edited" | "approved";
  actor: string;
  ts: string;
  note?: string | null;
  request_id?: string | null;
}

export interface HaRequest {
  request_id: string;
  section: string;
  drug: string;
  text: string;
  referenced_items: string[];
  source: SourceLocation;
  status: RequestStatus;
  linked_registration: RegistrationRecord[];
  linked_submissions: SubmissionDocument[];
  linked_precedents: HistoricPrecedent[];
  direction?: string | null;
  draft?: Draft | null;
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
  audit: AuditEntry[];
  invocations: Invocation[];
}

export interface CorrespondenceSummary {
  correspondence_id: string;
  filename: string;
  meta: CorrespondenceMeta;
  request_count: number;
  created_at: string;
  status: string;
}
