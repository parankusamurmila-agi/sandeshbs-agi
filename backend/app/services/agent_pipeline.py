"""The HA Request & Response agent.

1. extract_letter      - read the raw PDF directly and find every distinct HA
                          request/question, tagging each with the specific
                          drug/product it concerns. One forced tool-use
                          Bedrock Converse call.
2. link_request         - a Strands agent (_run_link_agent) decides which of
                          three deterministic, zero-LLM matchers to call for
                          a request's drug: match_registration_records (fuzzy
                          match against mock registration/application
                          tracking records, narrowed by issuing health
                          authority), match_submission_content (the matched
                          registration record's own `related_submission_doc_ids`),
                          and match_historic_precedents (prior HA deficiencies
                          for the same application number). Only the choice of
                          which tools to call is agentic -- each tool's return
                          value is exactly what the underlying deterministic
                          function produced, so the evidence shown to the
                          human reviewer is as deterministic as before.
3. draft_response       - a Strands agent (_run_draft_agent) drafts a
                          grounded, CTD/eCTD-style, region-aware response for
                          one request, using the matched registration
                          record(s), submission content, and historic
                          precedent -- passed in as plain context, not as
                          tools, so the agent can never draft against
                          evidence the human didn't already review at the
                          link step. Its only tool is select_template_tool,
                          so the one genuine judgment call (which regional
                          template fits) is agent-decided; the final
                          text/citations are produced via structured output.

Each step is still triggered on demand by its own FastAPI endpoint, kept
synchronous so it runs within API Gateway's request timeout -- no background
workers needed at this scale. match_registration_records/
match_submission_content/match_historic_precedents/_select_template remain
independently callable, deterministic, zero-LLM functions in their own
right -- the Strands agents are a thin orchestration layer on top of them,
not a replacement for them.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.models import BedrockModel, CacheConfig

from app.config import AWS_REGION, BEDROCK_MODEL_ID
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
    return json.loads((DATA_DIR / "registration_records.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_submissions() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "submissions.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_historic_responses() -> List[Dict[str, Any]]:
    return json.loads((DATA_DIR / "historic_responses.json").read_text(encoding="utf-8"))


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
    registration_records.json by fuzzy/substring match on `product`,
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
    (historic_responses.json's `precedent_id`s embed the NDA number they
    resolved, e.g. 'HIST-2015-NDA-198765-D04')."""
    app_tags = {tag for reg in linked_registration for tag in [_application_tag(reg.application_number)] if tag}
    if not app_tags:
        return []
    matches = [prec for prec in _load_historic_responses() if _application_tag(prec["precedent_id"]) in app_tags]
    return [HistoricPrecedent.model_validate(prec) for prec in matches]


def _usage_from_metrics(agent: Agent, model_id: str) -> UsageInfo:
    """Aggregate token usage across every underlying Bedrock call an agent run
    made (one Strands agent run can be several tool-call round trips) into a
    single UsageInfo, so one agent run still records as one Invocation --
    matching extract_letter/draft_response's existing one-call-one-Invocation
    semantics."""
    usage = agent.event_loop_metrics.accumulated_usage
    return UsageInfo(
        model_id=model_id,
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
        cache_read_input_tokens=usage.get("cacheReadInputTokens", 0),
        cache_write_input_tokens=usage.get("cacheWriteInputTokens", 0),
    )


def _run_link_agent(drug: Optional[str], health_authority: Optional[str]) -> Dict[str, Any]:
    """Builds a Strands agent that decides which of the three deterministic
    matchers to call for this drug. Each tool wrapper calls straight through to
    the real match_* function and stores the typed result in `state`; the
    agent's own final reply is never parsed for data -- only `state`, populated
    by the tools it actually chose to call, is read afterward."""
    state: Dict[str, List[Dict[str, Any]]] = {"registrations": [], "submissions": [], "precedents": []}

    @tool
    def match_registration_records_tool(
        drug: str, health_authority: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Look up registration/application tracking records for a drug, optionally
        narrowed by issuing health authority. Call this first.

        Args:
            drug: The drug/product name this request concerns.
            health_authority: The issuing health authority, to disambiguate when
                more than one registration shares the product name.

        Returns:
            Matching registration records.
        """
        records = match_registration_records(drug, health_authority)
        state["registrations"] = [r.model_dump() for r in records]
        return state["registrations"]

    @tool
    def match_submission_content_tool() -> List[Dict[str, Any]]:
        """Look up the submission documents/datasets tied to the registration
        record(s) already found by match_registration_records_tool -- call that
        tool first. Skip this if no registration record was found.

        Returns:
            Matching submission documents.
        """
        registrations = [RegistrationRecord.model_validate(r) for r in state["registrations"]]
        submissions = match_submission_content(registrations)
        state["submissions"] = [s.model_dump() for s in submissions]
        return state["submissions"]

    @tool
    def match_historic_precedents_tool() -> List[Dict[str, Any]]:
        """Look up prior HA deficiencies/responses resolved on the same application
        as the registration record(s) already found by match_registration_records_tool
        -- call that tool first. Skip this if no registration record was found.

        Returns:
            Matching historic precedents.
        """
        registrations = [RegistrationRecord.model_validate(r) for r in state["registrations"]]
        precedents = match_historic_precedents(registrations)
        state["precedents"] = [p.model_dump() for p in precedents]
        return state["precedents"]

    agent = Agent(
        # streaming=False: ConverseStream dropped mid-response ("Response ended
        # prematurely") in testing, while the plain Converse API (used by
        # call_tool for extract_letter) was reliable -- so agent runs use the
        # same non-streaming call.
        model=BedrockModel(
            model_id=BEDROCK_MODEL_ID,
            region_name=AWS_REGION,
            streaming=False,
            # Cache the (static, reused) system prompt so repeat link/draft calls
            # within Bedrock's cache TTL read it from cache instead of re-ingesting
            # it -- mirrors extract_letter's cachePoint (bedrock_client.call_tool).
            # strategy="auto" resolves to Anthropic caching for Claude model ids
            # (and no-ops for others); Bedrock silently skips the cache when the
            # prefix is under the model's min cacheable size, so it's always safe.
            # _usage_from_metrics already surfaces cacheRead/WriteInputTokens.
            cache_config=CacheConfig(strategy="auto"),
        ),
        tools=[match_registration_records_tool, match_submission_content_tool, match_historic_precedents_tool],
        system_prompt=get_prompt("ha-link-request"),
        # Strands' default callback handler streams model output straight to
        # stdout -- unwanted noise in a server process, and (confirmed against
        # real Bedrock) it can crash outright on a console codepage that can't
        # encode a character the model emits (e.g. cp1252 on Windows).
        callback_handler=None,
    )
    agent(f"drug: {drug or ''}\nissuing_health_authority: {health_authority or ''}")

    return {
        "registrations": state["registrations"],
        "submissions": state["submissions"],
        "precedents": state["precedents"],
        "usage": _usage_from_metrics(agent, BEDROCK_MODEL_ID),
    }


def link_request(
    drug: Optional[str], health_authority: Optional[str] = None
) -> tuple[List[RegistrationRecord], List[SubmissionDocument], List[HistoricPrecedent], UsageInfo]:
    """Agent-orchestrated replacement for calling match_registration_records /
    match_submission_content / match_historic_precedents directly: a Strands
    agent decides which of those three (tool-wrapped, otherwise unchanged)
    deterministic lookups to call for this drug. Only the choice of which tools
    to call is agentic -- each tool's return value is exactly what the
    underlying deterministic function produced."""
    result = _run_link_agent(drug, health_authority)
    return (
        [RegistrationRecord.model_validate(r) for r in result["registrations"]],
        [SubmissionDocument.model_validate(s) for s in result["submissions"]],
        [HistoricPrecedent.model_validate(p) for p in result["precedents"]],
        result["usage"],
    )


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


class _DraftOutput(BaseModel):
    text: str
    citations: List[str] = Field(default_factory=list)


def _run_draft_agent(payload: Dict[str, Any]) -> tuple[Dict[str, Any], UsageInfo]:
    """Builds a Strands agent with one tool, select_template_tool, so the agent
    itself decides which regional template fits (today's one piece of
    draft-time Python judgment) instead of Python pre-selecting it. All
    evidence stays plain context, exactly as before -- the agent gets no
    evidence-fetching tools, so it can never draft against anything the human
    didn't already review at the link step."""
    state: Dict[str, Any] = {"template": None}

    @tool
    def select_template_tool(health_authority: Optional[str] = None) -> Dict[str, Any]:
        """Select the CTD/eCTD response template and section structure for the
        given health authority. Call this once, before drafting.

        Args:
            health_authority: The matched registration record's health authority
                (or the letter's issuing health authority if nothing was linked).

        Returns:
            The selected template: template_id, name, and section list. Falls
            back to the generic template if nothing matches.
        """
        template = _select_template(health_authority)
        state["template"] = template
        return template or {}

    agent = Agent(
        # streaming=False: ConverseStream dropped mid-response ("Response ended
        # prematurely") in testing, while the plain Converse API (used by
        # call_tool for extract_letter) was reliable -- so agent runs use the
        # same non-streaming call.
        model=BedrockModel(
            model_id=BEDROCK_MODEL_ID,
            region_name=AWS_REGION,
            streaming=False,
            # Cache the (static, reused) system prompt so repeat link/draft calls
            # within Bedrock's cache TTL read it from cache instead of re-ingesting
            # it -- mirrors extract_letter's cachePoint (bedrock_client.call_tool).
            # strategy="auto" resolves to Anthropic caching for Claude model ids
            # (and no-ops for others); Bedrock silently skips the cache when the
            # prefix is under the model's min cacheable size, so it's always safe.
            # _usage_from_metrics already surfaces cacheRead/WriteInputTokens.
            cache_config=CacheConfig(strategy="auto"),
        ),
        tools=[select_template_tool],
        system_prompt=get_prompt("ha-draft-response"),
        callback_handler=None,
    )
    # `agent.structured_output(...)` as a separate call after the fact is deprecated
    # (and, confirmed against real Bedrock, never actually runs the tool loop --
    # it forces the output schema directly, so select_template_tool never gets
    # called). Passing structured_output_model into the same invocation runs the
    # normal tool loop first and *then* forces the final schema.
    agent_result = agent(json.dumps(payload, indent=2), structured_output_model=_DraftOutput)

    result = agent_result.structured_output.model_dump()
    result["template_id"] = state["template"]["template_id"] if state["template"] else None
    return result, _usage_from_metrics(agent, BEDROCK_MODEL_ID)


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

    payload = {
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
        "health_authority": region_ha,
        "user_direction": direction,
    }
    result, usage = _run_draft_agent(payload)
    draft = Draft.model_validate(result)
    return draft, usage
