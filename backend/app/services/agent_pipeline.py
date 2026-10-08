"""The HA Request & Response agent.

1. extract_letter               - read the raw PDF directly and find every
                                   distinct HA request/question, tagging each
                                   with the specific drug/product it concerns.
2. match_registration_records    - deterministic (zero-LLM) lookup of a
                                   request's drug against the mock
                                   registration/application tracking records,
                                   optionally narrowed by issuing health
                                   authority.
   match_submission_content      - deterministic lookup of the submission
                                   documents/datasets tied to the matched
                                   registration record(s) (via their own
                                   `related_submission_doc_ids`).
   match_historic_precedents     - deterministic lookup of prior HA
                                   deficiencies/responses for the same
                                   application number, for precedent.
3. draft_response               - draft a grounded, CTD/eCTD-style, region-
                                   aware response for one request, using the
                                   matched registration record(s), submission
                                   content, and historic precedent as
                                   evidence, with a template selected by
                                   region.

Steps 1 and 3 are each one forced tool-use Bedrock Converse call; step 2's
three matchers are plain Python with no model call. Kept deliberately
separate and synchronous so the orchestrating FastAPI endpoints can run them
on demand within API Gateway's request timeout -- no background workers or
autonomous looping needed for a hackathon-scale demo.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models import (
    CorrespondenceMeta,
    Draft,
    ExtractedRequest,
    HaRequest,
    HistoricPrecedent,
    RegistrationRecord,
    SubmissionDocument,
)
from app.services.bedrock_client import BedrockToolCallError, UsageInfo, call_tool
from app.services.prompts import get_prompt

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def _load_templates() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "templates.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_registration_records() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "mock_registration_records.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_submissions() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "mock_submissions.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_historic_responses() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "mock_historic_responses.json").read_text(encoding="utf-8"))


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "description": "Letter-level metadata, best-effort from the first page/letterhead.",
            "properties": {
                "applicant": {"type": "string"},
                "product": {
                    "type": "string",
                    "description": (
                        "Primary/lead product name if the letter is single-product; if the letter "
                        "covers multiple products, name the lead product here and rely on each "
                        "request's own `drug` field for per-request attribution."
                    ),
                },
                "letter_date": {"type": "string"},
                "source": {"type": "string", "description": "Issuing health authority, e.g. 'FDA', 'EMA', 'Health Canada'."},
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
                    "drug": {
                        "type": "string",
                        "description": (
                            "The specific drug/product this request concerns, verbatim as named in the "
                            "letter (brand name and/or active ingredient/INN). Required on every request, "
                            "even if the letter only discusses one product overall -- repeat that "
                            "product's name on every request in that case."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "A clear, plain-language rephrasing of this request/question so a reviewer can "
                            "understand it at a glance -- NOT a verbatim copy-paste from the letter. "
                            "Preserve the full meaning and every actionable detail, just in accessible "
                            "wording. The exact original wording still lives in `source.quote` for citation "
                            "purposes, so this field is free to paraphrase."
                        ),
                    },
                    "referenced_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Named documents/datasets this request mentions (e.g. CSR, TLFs, fdaclinpharmreqbaselab).",
                    },
                    "source": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer", "description": "1-based page number in the PDF where this request appears."},
                            "quote": {
                                "type": "string",
                                "description": (
                                    "A short (<=25 words) EXACT, character-for-character quote copied "
                                    "straight from that page, marking where the request begins -- this is "
                                    "the citation used to locate and highlight the request in the original "
                                    "PDF, so it must match the source text precisely (unlike `text`, which "
                                    "is intentionally rephrased)."
                                ),
                            },
                        },
                        "required": ["page", "quote"],
                    },
                },
                "required": ["request_id", "section", "drug", "text", "source"],
            },
        },
    },
    "required": ["meta", "requests"],
}

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "registration_ids and/or related_submission_doc_ids actually cited in the text.",
        },
    },
    "required": ["text"],
}

_REGION_TERMINOLOGY: Dict[str, Dict[str, str]] = {
    "FDA": {
        "authority_name": "U.S. Food and Drug Administration (FDA)",
        "review_division": "CDER/CBER",
        "application_label": "NDA/BLA",
        "deficiency_label": "Complete Response Letter (CRL) deficiency",
        "resubmission_label": "Class 1/Class 2 resubmission",
    },
    "EMA": {
        "authority_name": "European Medicines Agency (EMA)",
        "review_division": "CHMP",
        "application_label": "Marketing Authorisation Application (MAA)",
        "deficiency_label": "List of Questions / List of Outstanding Issues",
        "resubmission_label": "response to the List of Questions",
    },
    "HEALTH CANADA": {
        "authority_name": "Health Canada",
        "review_division": "Therapeutic Products Directorate (TPD)",
        "application_label": "New Drug Submission (NDS) / Abbreviated New Drug Submission (ANDS)",
        "deficiency_label": "Notice of Non-Compliance (NON) / Notice of Deficiency (NOD)",
        "resubmission_label": "NON/NOD response",
    },
    "VIETNAM": {
        "authority_name": "Drug Administration of Vietnam (DAV), Ministry of Health",
        "review_division": "Drug Registration Department",
        "application_label": "drug registration dossier / variation dossier",
        "deficiency_label": "Deficiency Letter (DL) on a variation dossier",
        "resubmission_label": "response dossier",
    },
    "LATVIA": {
        "authority_name": "State Agency of Medicines (Latvia)",
        "review_division": "Medicinal Products Registration Department",
        "application_label": "variation procedure (Type IB/II)",
        "deficiency_label": "variation deficiency",
        "resubmission_label": "variation response",
    },
    "HUNGARY": {
        "authority_name": "National Institute of Pharmacy and Nutrition (OGYEI), Hungary, as Concerned Member State (CMS)",
        "review_division": "CMS Assessment Team",
        "application_label": "Decentralised Procedure (DCP) application",
        "deficiency_label": "Day 100 CMS comments / List of Questions",
        "resubmission_label": "Day 100 response",
    },
}
_DEFAULT_TERMINOLOGY = {
    "authority_name": "the reviewing health authority",
    "review_division": "the relevant review division",
    "application_label": "the marketing application",
    "deficiency_label": "deficiency",
    "resubmission_label": "resubmission",
}


def _region_terminology(health_authority: Optional[str]) -> Dict[str, str]:
    if not health_authority:
        return _DEFAULT_TERMINOLOGY
    key = health_authority.strip().upper()
    for ha_key, terms in _REGION_TERMINOLOGY.items():
        if ha_key in key or key in ha_key:
            return terms
    return _DEFAULT_TERMINOLOGY


def _normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _product_tokens(product: str) -> List[str]:
    """'LUTATHERA (177Lu-DOTA0-Tyr3-Octreotate)' -> ['LUTATHERA', '177Lu-DOTA0-Tyr3-Octreotate']."""
    brand = product.split("(", 1)[0].strip()
    tokens = [brand] if brand else []
    paren = re.search(r"\((.*)\)", product)
    if paren:
        tokens.append(paren.group(1).strip())
    return tokens


def match_registration_records(
    drug: Optional[str], health_authority: Optional[str] = None
) -> List[RegistrationRecord]:
    """Deterministic, zero-LLM match of a request's `drug` against
    mock_registration_records.json by fuzzy/substring match on `product`,
    narrowed by `health_authority` (the correspondence's issuing HA) only
    when more than one registration shares the product name."""
    if not drug or not drug.strip():
        return []
    drug_key = _normalize(drug)
    if not drug_key:
        return []

    matches = [
        rec
        for rec in _load_registration_records()
        if any(
            tok and (drug_key in _normalize(tok) or _normalize(tok) in drug_key)
            for tok in _product_tokens(rec["product"])
        )
    ]

    if health_authority and len(matches) > 1:
        ha_key = _normalize(health_authority)
        narrowed = [
            m
            for m in matches
            if ha_key and (ha_key in _normalize(m["health_authority"]) or _normalize(m["health_authority"]) in ha_key)
        ]
        if narrowed:
            matches = narrowed

    return [RegistrationRecord.model_validate(m) for m in matches]


def match_submission_content(linked_registration: List[RegistrationRecord]) -> List[SubmissionDocument]:
    """Deterministic, zero-LLM lookup of the submission documents/datasets tied
    to the matched registration record(s), via their own `related_submission_doc_ids`
    -- the registration record is the authoritative source of which submission
    content is "affected" by that application, so no fuzzy matching is needed."""
    doc_ids = {doc_id for reg in linked_registration for doc_id in reg.related_submission_doc_ids}
    if not doc_ids:
        return []
    catalog = {sub["doc_id"]: sub for sub in _load_submissions()}
    return [SubmissionDocument.model_validate(catalog[doc_id]) for doc_id in doc_ids if doc_id in catalog]


_APPLICATION_TAG_RE = re.compile(r"NDA-\d+", re.IGNORECASE)


def _application_tag(value: str) -> Optional[str]:
    match = _APPLICATION_TAG_RE.search(value)
    return match.group(0).upper() if match else None


def match_historic_precedents(linked_registration: List[RegistrationRecord]) -> List[HistoricPrecedent]:
    """Deterministic, zero-LLM lookup of prior HA deficiencies/responses for the
    same application number as the matched registration record(s), for precedent
    (mock_historic_responses.json's `precedent_id`s embed the NDA number they
    resolved, e.g. 'HIST-2015-NDA-198765-D04')."""
    app_tags = {tag for reg in linked_registration for tag in [_application_tag(reg.application_number)] if tag}
    if not app_tags:
        return []
    matches = [prec for prec in _load_historic_responses() if _application_tag(prec["precedent_id"]) in app_tags]
    return [HistoricPrecedent.model_validate(prec) for prec in matches]


def _select_template(health_authority: Optional[str]) -> Optional[Dict[str, Any]]:
    """Picks the response template whose `region` matches the given health
    authority, falling back to the generic template (or the first template, if
    no generic one is defined)."""
    templates = _load_templates()
    if not templates:
        return None
    if health_authority:
        key = health_authority.strip().upper()
        for template in templates:
            region = (template.get("region") or "").strip().upper()
            if region and (region in key or key in region):
                return template
    for template in templates:
        if (template.get("region") or "").strip().upper() == "GENERIC":
            return template
    return templates[0]


def _as_list(value: Any) -> List[Any]:
    """Bedrock tool-use occasionally serializes an array field as a JSON string
    instead of a native array; normalize either shape to a real list.

    For large arrays (many requests on one letter), the model sometimes
    appends stray trailing content after a complete JSON array in that
    string (observed as a json.JSONDecodeError: "Extra data" at some offset
    deep in the string) -- recover the first complete JSON value with
    raw_decode instead of failing the whole upload over trailing junk."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(stripped)
            except json.JSONDecodeError as exc:
                raise BedrockToolCallError(f"Model returned malformed JSON for a list field: {exc}") from exc
        if isinstance(parsed, list):
            return parsed
    return []


def extract_letter(
    pdf_bytes: bytes, filename: str
) -> tuple[CorrespondenceMeta, List[ExtractedRequest], UsageInfo]:
    result, usage = call_tool(
        system_prompt=get_prompt("ha-extract-requests"),
        user_text=(
            "Extract the letter metadata and every distinct HA request from the attached "
            "PDF, following the schema and instructions in the system prompt."
        ),
        document_bytes=pdf_bytes,
        document_name=filename,
        document_format="pdf",
        tool_name="extract_requests",
        tool_description=(
            "Record letter metadata and every distinct HA request/question found, each tagged "
            "with the drug it concerns."
        ),
        tool_schema=EXTRACT_SCHEMA,
        max_tokens=8192,
    )
    meta = CorrespondenceMeta.model_validate(result.get("meta") or {})
    requests = [ExtractedRequest.model_validate(item) for item in _as_list(result.get("requests", []))]
    return meta, requests, usage


def draft_response(
    request: HaRequest,
    linked_registration: List[RegistrationRecord],
    linked_submissions: List[SubmissionDocument],
    linked_precedents: List[HistoricPrecedent],
    correspondence_meta: CorrespondenceMeta,
    direction: Optional[str] = None,
) -> tuple[Draft, UsageInfo]:
    registration_detail = [
        {
            "registration_id": reg.registration_id,
            "product": reg.product,
            "application_number": reg.application_number,
            "application_type": reg.application_type,
            "health_authority": reg.health_authority,
            "market": reg.market,
            "status": reg.status,
            "original_submission_date": reg.original_submission_date,
            "last_ha_correspondence": reg.last_ha_correspondence.model_dump() if reg.last_ha_correspondence else None,
            "response_due_date": reg.response_due_date,
        }
        for reg in linked_registration
    ]
    submission_detail = [sub.model_dump() for sub in linked_submissions]
    precedent_detail = [prec.model_dump() for prec in linked_precedents]

    region_ha = linked_registration[0].health_authority if linked_registration else correspondence_meta.source
    template = _select_template(region_ha)

    user_text = json.dumps(
        {
            "question": {
                "request_id": request.request_id,
                "section": request.section,
                "drug": request.drug,
                "text": request.text,
            },
            "linked_registration_records": registration_detail,
            "linked_submission_content": submission_detail,
            "linked_historic_precedents": precedent_detail,
            "region_terminology": _region_terminology(region_ha),
            "template": template,
            "user_direction": direction,
        },
        indent=2,
    )
    result, usage = call_tool(
        system_prompt=get_prompt("ha-draft-response"),
        user_text=user_text,
        tool_name="draft_response",
        tool_description="Draft a CTD/eCTD-style, region-appropriate response to this HA question.",
        tool_schema=DRAFT_SCHEMA,
        max_tokens=4096,
    )
    if "citations" in result:
        result["citations"] = _as_list(result["citations"])
    draft = Draft.model_validate(result)
    draft.template_id = template["template_id"] if template else None
    return draft, usage
