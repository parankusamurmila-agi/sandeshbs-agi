from __future__ import annotations

from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.models import (
    AuditEntry,
    Correspondence,
    CorrespondenceSummary,
    DraftPatchBody,
    DraftRequestBody,
    HaRequest,
    IngestPathBody,
)
from app.services import agent_runtime, batch_ingest, ingest, store

router = APIRouter()


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


def _ingest_one_document(filename: str, raw_bytes: bytes) -> Correspondence:
    """Create the record as `extracting` and kick off extraction (async in AWS,
    inline locally), returning the pending record immediately so the HTTP
    request never blocks on the model."""
    correspondence = ingest.create_pending_correspondence(filename, raw_bytes)
    ingest.trigger_extract(correspondence.correspondence_id)
    # Re-read so the response reflects the post-trigger state: still
    # "extracting" in AWS (async), already "extracted" locally (inline).
    return store.get_correspondence(correspondence.correspondence_id) or correspondence


@router.post("/correspondence", response_model=List[Correspondence])
async def upload_correspondence(files: List[UploadFile] = File(...)) -> List[Correspondence]:
    results: List[Correspondence] = []
    for file in files:
        raw_bytes = await file.read()
        if not raw_bytes:
            continue
        results.append(_ingest_one_document(file.filename or "correspondence.pdf", raw_bytes))

    if not results:
        raise HTTPException(status_code=400, detail="No valid files uploaded")
    return results


@router.post("/correspondence/from-path", response_model=List[Correspondence])
async def ingest_from_path(body: IngestPathBody) -> List[Correspondence]:
    try:
        documents = batch_ingest.list_documents_at_path(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not documents:
        raise HTTPException(status_code=404, detail=f"No .pdf/.docx documents found at '{body.path}'")

    return [_ingest_one_document(filename, raw_bytes) for filename, raw_bytes in documents]


@router.get("/correspondence", response_model=List[CorrespondenceSummary])
async def list_correspondence() -> List[CorrespondenceSummary]:
    return store.list_correspondences()


@router.get("/correspondence/{correspondence_id}", response_model=Correspondence)
async def get_correspondence(correspondence_id: str) -> Correspondence:
    return _get_correspondence_or_404(correspondence_id)


@router.get("/correspondence/{correspondence_id}/pdf")
async def get_correspondence_pdf(correspondence_id: str) -> Response:
    correspondence = _get_correspondence_or_404(correspondence_id)
    pdf_bytes = store.get_pdf_bytes(correspondence)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post(
    "/correspondence/{correspondence_id}/requests/{request_id}/link",
    response_model=HaRequest,
)
async def link_registration(correspondence_id: str, request_id: str) -> HaRequest:
    correspondence = _get_correspondence_or_404(correspondence_id)
    req = _get_request_or_404(correspondence, request_id)

    req.linked_registration, req.linked_submissions, req.linked_precedents, usage = agent_runtime.link_request(
        req.drug, correspondence.meta.source
    )
    if req.status == "extracted":
        req.status = "linked"

    note = (
        f"Matched {len(req.linked_registration)} registration record(s), "
        f"{len(req.linked_submissions)} submission document(s), and "
        f"{len(req.linked_precedents)} historic precedent(s) for '{req.drug}'."
        if req.linked_registration
        else f"No registration record matched for '{req.drug}'."
    )
    correspondence.audit.append(AuditEntry(action="linked", actor="agent", note=note, request_id=req.request_id))
    correspondence.invocations.append(ingest.build_invocation("link", req.request_id, usage))

    store.put_correspondence(correspondence)
    return req


@router.post(
    "/correspondence/{correspondence_id}/requests/{request_id}/draft",
    response_model=HaRequest,
)
async def generate_draft(correspondence_id: str, request_id: str, body: DraftRequestBody) -> HaRequest:
    correspondence = _get_correspondence_or_404(correspondence_id)
    req = _get_request_or_404(correspondence, request_id)

    if req.status == "extracted":
        raise HTTPException(
            status_code=400,
            detail="Link a registration record (POST .../link) before generating a draft.",
        )

    req.direction = body.direction
    req.draft, usage = agent_runtime.draft_response(
        req,
        req.linked_registration,
        req.linked_submissions,
        req.linked_precedents,
        correspondence.meta,
        body.direction,
    )
    req.status = "drafted"
    correspondence.audit.append(AuditEntry(action="drafted", actor="agent", request_id=req.request_id))
    correspondence.invocations.append(ingest.build_invocation("draft", req.request_id, usage))

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
        correspondence.audit.append(
            AuditEntry(action="edited", actor=body.actor, note="draft text edited", request_id=req.request_id)
        )

    if body.action == "approve":
        req.status = "approved"
        correspondence.audit.append(AuditEntry(action="approved", actor=body.actor, request_id=req.request_id))

    store.put_correspondence(correspondence)
    return req
