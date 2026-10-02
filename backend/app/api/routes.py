from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models import (
    AuditEntry,
    Correspondence,
    CorrespondenceSummary,
    Draft,
    DraftPatchBody,
    DraftRequestBody,
    HaRequest,
)
from app.services import agent_pipeline, store
from app.services.pdf_extractor import extract_tagged_text

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_correspondence_or_404(correspondence_id: str) -> Correspondence:
    correspondence = store.get_correspondence(correspondence_id)
    if correspondence is None:
        raise HTTPException(status_code=404, detail="Correspondence not found")
    return correspondence


def _get_request_or_404(correspondence: Correspondence, request_id: str) -> HaRequest:
    for req in correspondence.requests:
        if req.request_id == request_id:
            return req
    raise HTTPException(status_code=404, detail="Request not found in this correspondence")


@router.post("/correspondence", response_model=Correspondence)
async def upload_correspondence(file: UploadFile = File(...)) -> Correspondence:
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    tagged_text = extract_tagged_text(pdf_bytes)
    meta, extracted = agent_pipeline.extract_letter(tagged_text)

    correspondence = Correspondence(filename=file.filename or "correspondence.pdf", s3_key="", meta=meta)
    correspondence.s3_key = store.save_pdf(correspondence.correspondence_id, correspondence.filename, pdf_bytes)
    correspondence.requests = [HaRequest(**item.model_dump()) for item in extracted]

    store.put_correspondence(correspondence)
    return correspondence


@router.get("/correspondence", response_model=List[CorrespondenceSummary])
async def list_correspondence() -> List[CorrespondenceSummary]:
    return store.list_correspondences()


@router.get("/correspondence/{correspondence_id}", response_model=Correspondence)
async def get_correspondence(correspondence_id: str) -> Correspondence:
    return _get_correspondence_or_404(correspondence_id)


@router.post(
    "/correspondence/{correspondence_id}/requests/{request_id}/draft",
    response_model=HaRequest,
)
async def generate_draft(correspondence_id: str, request_id: str, body: DraftRequestBody) -> HaRequest:
    correspondence = _get_correspondence_or_404(correspondence_id)
    req = _get_request_or_404(correspondence, request_id)

    req.direction = body.direction
    req.linked_evidence = agent_pipeline.link_evidence(req)
    req.draft = agent_pipeline.draft_response(req, req.linked_evidence, body.direction)
    req.status = "drafted"
    req.audit.append(AuditEntry(action="drafted", actor="agent"))

    store.put_correspondence(correspondence)
    return req


@router.patch(
    "/correspondence/{correspondence_id}/requests/{request_id}/draft",
    response_model=HaRequest,
)
async def update_draft(correspondence_id: str, request_id: str, body: DraftPatchBody) -> HaRequest:
    correspondence = _get_correspondence_or_404(correspondence_id)
    req = _get_request_or_404(correspondence, request_id)

    if req.draft is None:
        raise HTTPException(status_code=400, detail="No draft exists yet for this request")

    if body.text is not None and body.text != req.draft.text:
        req.draft.text = body.text
        req.audit.append(AuditEntry(action="edited", actor=body.actor, note="draft text edited"))

    if body.action == "approve":
        req.status = "approved"
        req.audit.append(AuditEntry(action="approved", actor=body.actor))

    store.put_correspondence(correspondence)
    return req


@router.get(
    "/correspondence/{correspondence_id}/requests/{request_id}/audit",
    response_model=List[AuditEntry],
)
async def get_audit(correspondence_id: str, request_id: str) -> List[AuditEntry]:
    correspondence = _get_correspondence_or_404(correspondence_id)
    req = _get_request_or_404(correspondence, request_id)
    return req.audit
