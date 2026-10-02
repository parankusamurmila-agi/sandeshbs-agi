"""Persistence: S3 for the original PDF, DynamoDB for the correspondence record.

When `LOCAL_STORE=true` (local dev without provisioned AWS resources), both
are swapped for an in-process dict / local-disk folder so the API is runnable
with zero AWS setup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from app.config import DYNAMODB_TABLE, LOCAL_STORE, S3_BUCKET
from app.models import Correspondence, CorrespondenceSummary

_LOCAL_PDF_DIR = Path(__file__).resolve().parent.parent.parent / ".local_store" / "pdfs"
_local_correspondences: Dict[str, dict] = {}

_dynamodb_table = None
_s3_client = None


def _get_table():
    global _dynamodb_table
    if _dynamodb_table is None:
        import boto3

        _dynamodb_table = boto3.resource("dynamodb").Table(DYNAMODB_TABLE)
    return _dynamodb_table


def _get_s3():
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def save_pdf(correspondence_id: str, filename: str, pdf_bytes: bytes) -> str:
    s3_key = f"correspondence/{correspondence_id}/{filename}"
    if LOCAL_STORE:
        _LOCAL_PDF_DIR.mkdir(parents=True, exist_ok=True)
        (_LOCAL_PDF_DIR / f"{correspondence_id}_{filename}").write_bytes(pdf_bytes)
    else:
        _get_s3().put_object(Bucket=S3_BUCKET, Key=s3_key, Body=pdf_bytes, ContentType="application/pdf")
    return s3_key


def put_correspondence(correspondence: Correspondence) -> None:
    item = correspondence.model_dump(mode="json")
    if LOCAL_STORE:
        _local_correspondences[correspondence.correspondence_id] = item
    else:
        _get_table().put_item(Item=item)


def get_correspondence(correspondence_id: str) -> Optional[Correspondence]:
    if LOCAL_STORE:
        item = _local_correspondences.get(correspondence_id)
    else:
        response = _get_table().get_item(Key={"correspondence_id": correspondence_id})
        item = response.get("Item")
    return Correspondence.model_validate(item) if item else None


def list_correspondences() -> List[CorrespondenceSummary]:
    if LOCAL_STORE:
        items = list(_local_correspondences.values())
    else:
        items = _get_table().scan().get("Items", [])
    return [
        CorrespondenceSummary(
            correspondence_id=item["correspondence_id"],
            filename=item["filename"],
            meta=item.get("meta", {}),
            request_count=len(item.get("requests", [])),
            created_at=item["created_at"],
        )
        for item in items
    ]
