"""Pydantic schemas for the HA Request & Response Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid4())


RequestStatus = Literal["extracted", "drafted", "approved"]
AuditAction = Literal["drafted", "edited", "approved"]


class SourceLocation(BaseModel):
    page: int
    paragraph: int


class LinkedEvidence(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    rationale: str


class Draft(BaseModel):
    text: str
    citations: List[str] = Field(default_factory=list)


class AuditEntry(BaseModel):
    action: AuditAction
    actor: str
    ts: str = Field(default_factory=_now)
    note: Optional[str] = None


class ExtractedRequest(BaseModel):
    """Schema the LLM must populate for every HA request found in the letter."""

    request_id: str
    section: str
    text: str
    referenced_items: List[str] = Field(default_factory=list)
    source: SourceLocation


class HaRequest(ExtractedRequest):
    """Stored, stateful version of an extracted request."""

    status: RequestStatus = "extracted"
    linked_evidence: List[LinkedEvidence] = Field(default_factory=list)
    direction: Optional[str] = None
    draft: Optional[Draft] = None
    audit: List[AuditEntry] = Field(default_factory=list)


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
    status: Literal["extracted"] = "extracted"
    requests: List[HaRequest] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class CorrespondenceSummary(BaseModel):
    correspondence_id: str
    filename: str
    meta: CorrespondenceMeta
    request_count: int
    created_at: str


class DraftRequestBody(BaseModel):
    direction: Optional[str] = None


class DraftPatchBody(BaseModel):
    text: Optional[str] = None
    action: Optional[Literal["edit", "approve"]] = None
    actor: str = "user"
