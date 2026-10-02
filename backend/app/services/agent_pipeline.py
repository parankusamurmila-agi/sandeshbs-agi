"""The three-step HA Request & Response agent.

1. extract_requests  - find every distinct HA request/deficiency in the letter.
2. link_evidence      - pick relevant submission/historic-precedent records for one request.
3. draft_response     - draft a grounded response for one request.

Each step is one forced tool-use Bedrock Converse call, kept deliberately
separate and synchronous so the orchestrating FastAPI endpoints can run them
on demand within API Gateway's request timeout -- no background workers or
autonomous looping needed for a hackathon-scale demo.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models import CorrespondenceMeta, Draft, ExtractedRequest, HaRequest, LinkedEvidence
from app.services.bedrock_client import call_tool

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def _load_submissions() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "mock_submissions.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_historic_responses() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "mock_historic_responses.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_templates() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "templates.json").read_text(encoding="utf-8"))


def _evidence_catalog() -> List[Dict[str, str]]:
    """Submissions + historic precedent, normalized into one candidate pool."""
    catalog: List[Dict[str, str]] = []
    for sub in _load_submissions():
        catalog.append(
            {
                "doc_id": sub["doc_id"],
                "title": sub["title"],
                "doc_type": sub["doc_type"],
                "detail": sub["summary"],
            }
        )
    for hist in _load_historic_responses():
        catalog.append(
            {
                "doc_id": hist["precedent_id"],
                "title": f"Prior precedent: {hist['prior_deficiency'][:80]}",
                "doc_type": "Historic Precedent",
                "detail": (
                    f"Prior deficiency: {hist['prior_deficiency']} "
                    f"Prior response: {hist['prior_response_summary']} "
                    f"Outcome: {hist['outcome']}"
                ),
            }
        )
    return catalog


def _catalog_by_id() -> Dict[str, Dict[str, str]]:
    return {entry["doc_id"]: entry for entry in _evidence_catalog()}


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "description": "Letter-level metadata, best-effort from the first page.",
            "properties": {
                "applicant": {"type": "string"},
                "product": {"type": "string"},
                "letter_date": {"type": "string"},
                "source": {"type": "string", "description": "e.g. 'FDA', 'EMA'."},
            },
        },
        "requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "e.g. '1', '9a', '9b' - matches the letter's own numbering/lettering.",
                    },
                    "section": {"type": "string"},
                    "text": {"type": "string", "description": "Full verbatim text of this request/deficiency."},
                    "referenced_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Named documents/datasets this request mentions (e.g. CSR, TLFs, fdaclinpharmreqbaselab).",
                    },
                    "source": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer"},
                            "paragraph": {"type": "integer"},
                        },
                        "required": ["page", "paragraph"],
                    },
                },
                "required": ["request_id", "section", "text", "source"],
            },
        }
    },
    "required": ["meta", "requests"],
}

LINK_SCHEMA = {
    "type": "object",
    "properties": {
        "linked_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "title": {"type": "string"},
                    "doc_type": {"type": "string"},
                    "rationale": {"type": "string", "description": "One sentence: why this record is relevant."},
                },
                "required": ["doc_id", "title", "doc_type", "rationale"],
            },
        }
    },
    "required": ["linked_evidence"],
}

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "doc_ids of linked evidence actually cited in the text.",
        },
    },
    "required": ["text"],
}

EXTRACT_SYSTEM_PROMPT = """You are a regulatory affairs assistant. You will be given the full text of a \
health-authority (HA) deficiency/correspondence letter, with every paragraph wrapped in a \
tag like <p page="N" idx="K">...</p>.

First, extract letter-level metadata (applicant/sponsor name, product name, letter date, \
issuing authority) from the opening paragraphs; leave a field blank if not stated.

Then identify every distinct request or deficiency the HA is asking the applicant to address. \
Treat each numbered item (e.g. "1.", "2.") as a separate request. If a numbered item has \
lettered sub-items (e.g. "a.", "b."), treat EACH lettered sub-item as its own separate \
request with request_id formatted as "<number><letter>" (e.g. "9a", "9b"), not the parent \
number alone. Use the exact page/paragraph of the tag the request text came from. Ignore \
boilerplate (salutation, signature block, legal disclaimers) -- only extract actionable \
requests/deficiencies. Call the extract_requests tool exactly once with every request found."""

LINK_SYSTEM_PROMPT = """You are a regulatory affairs assistant selecting supporting evidence for a \
single HA deficiency response. You will be given the deficiency text and a candidate pool of \
submission documents/datasets and prior precedent responses. Select ONLY the candidates that \
are plausibly relevant to responding to this specific deficiency (typically 1-4 items). For \
each selected candidate, give a one-sentence rationale tied to the deficiency text. Do not \
invent doc_ids that are not in the candidate pool. Call the link_evidence tool exactly once."""

DRAFT_SYSTEM_PROMPT = """You are a regulatory affairs assistant drafting a response to a single HA \
deficiency. Ground your response ONLY in: the deficiency text, the supplied linked evidence \
(cite them by doc_id in `citations`), the response template's section structure, any user-provided \
direction, and the prior precedent responses if supplied. Do not fabricate data, dates, or \
commitments that are not implied by the inputs. Follow the template's section headings as the \
structure of `text` (use short section headers inline). Call the draft_response tool exactly once."""


def _as_list(value: Any) -> List[Any]:
    """Bedrock tool-use occasionally serializes an array field as a JSON string
    instead of a native array; normalize either shape to a real list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    return []


def extract_letter(tagged_letter_text: str) -> tuple[CorrespondenceMeta, List[ExtractedRequest]]:
    result = call_tool(
        system_prompt=EXTRACT_SYSTEM_PROMPT,
        user_text=tagged_letter_text,
        tool_name="extract_requests",
        tool_description="Record letter metadata and every distinct HA request/deficiency found.",
        tool_schema=EXTRACT_SCHEMA,
        max_tokens=8192,
    )
    meta = CorrespondenceMeta.model_validate(result.get("meta") or {})
    requests = [ExtractedRequest.model_validate(item) for item in _as_list(result.get("requests", []))]
    return meta, requests


def link_evidence(request: HaRequest) -> List[LinkedEvidence]:
    catalog = _evidence_catalog()
    user_text = json.dumps(
        {
            "deficiency": {
                "request_id": request.request_id,
                "section": request.section,
                "text": request.text,
                "referenced_items": request.referenced_items,
            },
            "candidate_pool": catalog,
        },
        indent=2,
    )
    result = call_tool(
        system_prompt=LINK_SYSTEM_PROMPT,
        user_text=user_text,
        tool_name="link_evidence",
        tool_description="Select relevant evidence records for this deficiency.",
        tool_schema=LINK_SCHEMA,
        max_tokens=2048,
    )
    return [LinkedEvidence.model_validate(item) for item in _as_list(result.get("linked_evidence", []))]


def draft_response(
    request: HaRequest,
    linked_evidence: List[LinkedEvidence],
    direction: Optional[str] = None,
) -> Draft:
    by_id = _catalog_by_id()
    evidence_detail = [
        {
            "doc_id": ev.doc_id,
            "title": ev.title,
            "doc_type": ev.doc_type,
            "detail": by_id.get(ev.doc_id, {}).get("detail", ""),
            "rationale": ev.rationale,
        }
        for ev in linked_evidence
    ]
    templates = _load_templates()
    user_text = json.dumps(
        {
            "deficiency": {
                "request_id": request.request_id,
                "section": request.section,
                "text": request.text,
            },
            "linked_evidence": evidence_detail,
            "template": templates[0] if templates else None,
            "user_direction": direction,
        },
        indent=2,
    )
    result = call_tool(
        system_prompt=DRAFT_SYSTEM_PROMPT,
        user_text=user_text,
        tool_name="draft_response",
        tool_description="Draft the response text for this deficiency.",
        tool_schema=DRAFT_SCHEMA,
        max_tokens=4096,
    )
    if "citations" in result:
        result["citations"] = _as_list(result["citations"])
    return Draft.model_validate(result)
