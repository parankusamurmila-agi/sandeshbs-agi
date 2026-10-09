"""Pydantic schemas for the HA Request & Response Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid4())


RequestStatus = Literal["extracted", "linked", "drafted", "approved"]
AuditAction = Literal["uploaded", "extracted", "linked", "drafted", "edited", "approved"]


class SourceLocation(BaseModel):
    page: int
    quote: str


class RegistrationCorrespondence(BaseModel):
    type: Optional[str] = None
    date: Optional[str] = None
    reference: Optional[str] = None


class RegistrationRecord(BaseModel):
    """Mirrors one entry of data/registration_records.json."""

    registration_id: str
    product: str
    application_number: str
    application_type: str
    health_authority: str
    market: str
    status: str
    original_submission_date: Optional[str] = None
    last_ha_correspondence: Optional[RegistrationCorrespondence] = None
    response_due_date: Optional[str] = None
    related_submission_doc_ids: List[str] = Field(default_factory=list)


class SubmissionDocument(BaseModel):
    """Mirrors one entry of data/submissions.json."""

    doc_id: str
    title: str
    doc_type: str
    module: Optional[str] = None
    summary: str


class HistoricPrecedent(BaseModel):
    """Mirrors one entry of data/historic_responses.json."""

    precedent_id: str
    prior_deficiency: str
    prior_response_summary: str
    outcome: str


class Draft(BaseModel):
    text: str
    citations: List[str] = Field(default_factory=list)
    template_id: Optional[str] = None


class AuditEntry(BaseModel):
    action: AuditAction
    actor: str
    ts: str = Field(default_factory=_now)
    note: Optional[str] = None
    request_id: Optional[str] = None


class ExtractedRequest(BaseModel):
    """Schema the LLM must populate for every HA request found in the letter."""

    request_id: str
    section: str
    drug: str
    text: str
    referenced_items: List[str] = Field(default_factory=list)
    source: SourceLocation


class HaRequest(ExtractedRequest):
    """Stored, stateful version of an extracted request."""

    status: RequestStatus = "extracted"
    linked_registration: List[RegistrationRecord] = Field(default_factory=list)
    linked_submissions: List[SubmissionDocument] = Field(default_factory=list)
    linked_precedents: List[HistoricPrecedent] = Field(default_factory=list)
    direction: Optional[str] = None
    draft: Optional[Draft] = None


class Invocation(BaseModel):
    """One agentic/LLM step: the letter-level `extract` call (request_id=None),
    or a per-question `link` or `draft` agent run (each may make several
    underlying Bedrock calls, aggregated into one Invocation)."""

    invocation_id: str = Field(default_factory=_uuid)
    kind: Literal["extract", "link", "draft"]
    model_config = ConfigDict(protected_namespaces=())

    request_id: Optional[str] = None
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    ts: str = Field(default_factory=_now)


class CorrespondenceMeta(BaseModel):
    applicant: Optional[str] = None
    product: Optional[str] = None
    letter_date: Optional[str] = None
    source: Optional[str] = None


class Correspondence(BaseModel):
    correspondence_id: str = Field(default_factory=_uuid)
    s3_key: str
    filename: str
    meta: CorrespondenceMeta = Field(default_factory=CorrespondenceMeta)
    # "extracting" until the async extract worker finishes; then "extracted"
    # (or "failed"). Letters predating async ingestion are stored as
    # "extracted", which stays valid.
    status: Literal["extracting", "extracted", "failed"] = "extracting"
    requests: List[HaRequest] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    audit: List[AuditEntry] = Field(default_factory=list)
    invocations: List[Invocation] = Field(default_factory=list)


class CorrespondenceSummary(BaseModel):
    correspondence_id: str
    filename: str
    meta: CorrespondenceMeta
    request_count: int
    created_at: str
    status: str = "extracted"


class IngestPathBody(BaseModel):
    path: str


class DraftRequestBody(BaseModel):
    direction: Optional[str] = None


class DraftPatchBody(BaseModel):
    text: Optional[str] = None
    action: Optional[Literal["edit", "approve"]] = None
    actor: str = "user"
