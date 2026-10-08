"""Document ingestion split into a fast part and a slow part so uploads never
block on the model.

- create_pending_correspondence(): save the PDF, create a Correspondence with
  status="extracting", persist, return immediately (sub-second).
- trigger_extract(): kick off extraction. In AWS, async self-invoke of this
  same Lambda (InvocationType="Event") so the HTTP request returns right away,
  avoiding API Gateway's ~29s cap on large letters. Locally (LOCAL_STORE), run
  it inline since there's no Lambda to invoke.
- run_extract(): the slow worker -- read the PDF, run the one extract Bedrock
  call, fill in requests + status="extracted" (or "failed"), persist.

The frontend polls GET /correspondence/{id} until status leaves "extracting".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import LOCAL_STORE
from app.models import AuditEntry, Correspondence, HaRequest, Invocation
from app.services import agent_pipeline, doc_converter, store
from app.services.bedrock_client import UsageInfo, estimate_cost_usd


def build_invocation(kind: str, request_id: str | None, usage: UsageInfo) -> Invocation:
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


def create_pending_correspondence(filename: str, raw_bytes: bytes) -> Correspondence:
    """Save the document and record it as `extracting`; returns fast."""
    converted_note = None
    if doc_converter.is_docx(filename):
        pdf_bytes = doc_converter.convert_docx_to_pdf(raw_bytes)
        converted_note = f"Converted '{filename}' from Word (.docx) to PDF."
        filename = Path(filename).with_suffix(".pdf").name
    else:
        pdf_bytes = raw_bytes

    correspondence = Correspondence(filename=filename, s3_key="", status="extracting")
    correspondence.s3_key = store.save_pdf(correspondence.correspondence_id, correspondence.filename, pdf_bytes)
    correspondence.audit.append(
        AuditEntry(action="uploaded", actor="user", note=converted_note or f"Uploaded {filename}")
    )
    store.put_correspondence(correspondence)
    return correspondence


def trigger_extract(correspondence_id: str) -> None:
    """Start extraction. Async self-invoke in AWS; inline locally."""
    if LOCAL_STORE:
        run_extract(correspondence_id)
        return
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"task": "extract", "correspondence_id": correspondence_id}).encode("utf-8"),
    )


def run_extract(correspondence_id: str) -> None:
    """The slow worker: one extract Bedrock call, then persist the result."""
    correspondence = store.get_correspondence(correspondence_id)
    if correspondence is None:
        return
    try:
        pdf_bytes = store.get_pdf_bytes(correspondence)
        meta, extracted, usage = agent_pipeline.extract_letter(pdf_bytes, correspondence.filename)
        correspondence.meta = meta
        correspondence.requests = [HaRequest(**item.model_dump()) for item in extracted]
        correspondence.status = "extracted"
        correspondence.audit.append(
            AuditEntry(
                action="extracted",
                actor="agent",
                note=f"Extracted {len(correspondence.requests)} request(s) from the letter.",
            )
        )
        correspondence.invocations.append(build_invocation("extract", None, usage))
    except Exception as exc:  # noqa: BLE001 -- record any failure so the UI can surface it
        correspondence.status = "failed"
        correspondence.audit.append(
            AuditEntry(action="extracted", actor="agent", note=f"Extraction failed: {exc}")
        )
    store.put_correspondence(correspondence)
