from unittest.mock import MagicMock, patch

import pytest

from app.services import batch_ingest


def test_list_documents_at_path_local_requires_local_store_true(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_ingest, "LOCAL_STORE", False)
    with pytest.raises(ValueError):
        batch_ingest.list_documents_at_path(str(tmp_path))


def test_list_documents_at_path_local_lists_pdf_and_docx_only(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_ingest, "LOCAL_STORE", True)
    (tmp_path / "a.pdf").write_bytes(b"pdf-bytes")
    (tmp_path / "b.docx").write_bytes(b"docx-bytes")
    (tmp_path / "c.txt").write_bytes(b"ignored")

    documents = batch_ingest.list_documents_at_path(str(tmp_path))

    assert {name for name, _ in documents} == {"a.pdf", "b.docx"}
    assert dict(documents)["a.pdf"] == b"pdf-bytes"


def test_list_documents_at_path_local_requires_existing_directory(monkeypatch):
    monkeypatch.setattr(batch_ingest, "LOCAL_STORE", True)
    with pytest.raises(ValueError):
        batch_ingest.list_documents_at_path(r"C:\does\not\exist\at\all")


@patch("app.services.store.get_s3_client")
def test_list_documents_at_path_s3_parses_prefix_and_filters_keys(mock_get_s3_client):
    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "letters/"},  # folder placeholder, must be skipped
                {"Key": "letters/a.pdf"},
                {"Key": "letters/b.docx"},
                {"Key": "letters/notes.txt"},  # unsupported suffix, must be skipped
            ]
        }
    ]
    mock_s3.get_paginator.return_value = mock_paginator
    mock_s3.get_object.side_effect = lambda Bucket, Key: {
        "Body": MagicMock(read=lambda: f"bytes-for-{Key}".encode())
    }
    mock_get_s3_client.return_value = mock_s3

    documents = batch_ingest.list_documents_at_path("s3://my-bucket/letters/sub/prefix")

    mock_s3.get_paginator.assert_called_once_with("list_objects_v2")
    mock_paginator.paginate.assert_called_once_with(Bucket="my-bucket", Prefix="letters/sub/prefix")
    assert {name for name, _ in documents} == {"a.pdf", "b.docx"}
    assert dict(documents)["a.pdf"] == b"bytes-for-letters/a.pdf"
