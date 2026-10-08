"""Discovers multiple HA correspondence documents at a single location --
either an S3 prefix (for real/deployed use) or a local folder (dev-only,
when a Lambda would have no filesystem to point at anyway) -- so a user can
process a whole batch by giving one path instead of uploading file-by-file.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from app.config import LOCAL_STORE
from app.services import store

_SUPPORTED_SUFFIXES = (".pdf", ".docx")


def _list_s3(path: str) -> List[Tuple[str, bytes]]:
    bucket, _, prefix = path[5:].partition("/")
    s3 = store.get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    documents: List[Tuple[str, bytes]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not key.lower().endswith(_SUPPORTED_SUFFIXES):
                continue
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            documents.append((Path(key).name, body))
    return documents


def _list_local(path: str) -> List[Tuple[str, bytes]]:
    if not LOCAL_STORE:
        raise ValueError(
            "Local filesystem paths are only supported when LOCAL_STORE=true "
            "(a deployed Lambda cannot see your filesystem) -- use an s3:// path instead."
        )
    folder = Path(path)
    if not folder.is_dir():
        raise ValueError(f"'{path}' is not a local directory")
    return [
        (entry.name, entry.read_bytes())
        for entry in sorted(folder.iterdir())
        if entry.is_file() and entry.suffix.lower() in _SUPPORTED_SUFFIXES
    ]


def list_documents_at_path(path: str) -> List[Tuple[str, bytes]]:
    """Returns (filename, bytes) for every .pdf/.docx found at `path`,
    which is either `s3://bucket/prefix` or a local folder path."""
    if path.startswith("s3://"):
        return _list_s3(path)
    return _list_local(path)
