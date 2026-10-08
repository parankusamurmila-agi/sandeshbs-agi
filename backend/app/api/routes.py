from __future__ import annotations

from pathlib import Path
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
    Invocation,
)
from app.services import agent_pipeline, batch_ingest, doc_converter, store
from app.services.bedrock_client import UsageInfo, estimate_cost_usd

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


def _build_invocation(kind: str, request_id: str | None, usage: UsageInfo) -> Invocation:
    return Invocation(
        kind=kind,
        request_id=request_id,
        model_id=usage.model_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        estimated_cost_usd=estimate_cost_usd(usage),
    )


def _ingest_one_document(filename: str, raw_bytes: bytes) -> Correspondence:
    """Shared pipeline for one document, used by both the direct multi-file
    upload and the path-based batch ingestion -- each call produces exactly
    one Correspondence with exactly one `extract` Invocation."""
    converted_note = None
    if doc_converter.is_docx(filename):
        pdf_bytes = doc_converter.convert_docx_to_pdf(raw_bytes)
        converted_note = f"Converted '{filename}' from Word (.docx) to PDF."
        filename = Path(filename).with_suffix(".pdf").name
    else:
        pdf_bytes = raw_bytes

    meta, extracted, usage = agent_pipeline.extract_letter(pdf_bytes, filename)

    correspondence = Correspondence(filename=filename, s3_key="", meta=meta)
    correspondence.s3_key = store.save_pdf(correspondence.correspondence_id, correspondence.filename, pdf_bytes)
    correspondence.requests = [HaRequest(**item.model_dump()) for item in extracted]
    correspondence.audit.append(AuditEntry(action="uploaded", actor="user", note=converted_note or f"Uploaded {filename}"))
    correspondence.audit.append(
        AuditEntry(
            action="extracted",
            actor="agent",
            note=f"Extracted {len(correspondence.requests)} request(s) from the letter.",
        )
    )
    correspondence.invocations.append(_build_invocation("extract", None, usage))

    store.put_correspondence(correspondence)
    return correspondence


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

    req.linked_registration = agent_pipeline.match_registration_records(req.drug, correspondence.meta.source)
    req.linked_submissions = agent_pipeline.match_submission_content(req.linked_registration)
    req.linked_precedents = agent_pipeline.match_historic_precedents(req.linked_registration)
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
    req.draft, usage = agent_pipeline.draft_response(
        req,
        req.linked_registration,
        req.linked_submissions,
        req.linked_precedents,
        correspondence.meta,
        body.direction,
    )
    req.status = "drafted"
    correspondence.audit.append(AuditEntry(action="drafted", actor="agent", request_id=req.request_id))
    correspondence.invocations.append(_build_invocation("draft", req.request_id, usage))

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
