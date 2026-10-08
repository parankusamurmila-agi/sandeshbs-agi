from unittest.mock import patch

import pytest

from app.models import CorrespondenceMeta, HaRequest, SourceLocation
from app.services import agent_pipeline
from app.services.bedrock_client import BedrockToolCallError, UsageInfo

_USAGE = UsageInfo(model_id="us.anthropic.claude-sonnet-5", input_tokens=100, output_tokens=50)


def _sample_request(drug: str = "LUTATHERA") -> HaRequest:
    return HaRequest(
        request_id="1",
        section="Clinical and Statistical Comments",
        drug=drug,
        text="Submit the primary cleaned and verified data used to generate the CSR and TLFs.",
        referenced_items=["CSR", "TLFs"],
        source=SourceLocation(page=1, quote="Submit the primary cleaned and verified data"),
    )


@patch("app.services.agent_pipeline.call_tool")
def test_extract_letter_sends_pdf_as_document_block(mock_call_tool):
    mock_call_tool.return_value = (
        {
            "meta": {"applicant": "Teva Pharmaceuticals", "product": "LUTATHERA", "letter_date": "2016", "source": "FDA"},
            "requests": [
                {
                    "request_id": "1",
                    "section": "Clinical and Statistical Comments",
                    "drug": "LUTATHERA",
                    "text": "Submit the primary cleaned and verified data...",
                    "referenced_items": ["CSR", "TLFs"],
                    "source": {"page": 1, "quote": "Submit the primary cleaned and verified data"},
                }
            ],
        },
        _USAGE,
    )

    meta, requests, usage = agent_pipeline.extract_letter(b"%PDF-1.4 fake", "letter.pdf")

    assert meta.applicant == "Teva Pharmaceuticals"
    assert len(requests) == 1
    assert requests[0].drug == "LUTATHERA"
    assert requests[0].source.page == 1
    assert usage is _USAGE

    kwargs = mock_call_tool.call_args.kwargs
    assert kwargs["tool_name"] == "extract_requests"
    assert kwargs["document_bytes"] == b"%PDF-1.4 fake"
    assert kwargs["document_name"] == "letter.pdf"


def test_match_registration_records_matches_by_product_substring():
    matches = agent_pipeline.match_registration_records("LUTATHERA")
    assert {m.health_authority for m in matches} == {"FDA", "EMA"}


def test_match_registration_records_narrows_by_health_authority():
    matches = agent_pipeline.match_registration_records("LUTATHERA", health_authority="FDA")
    assert len(matches) == 1 and matches[0].health_authority == "FDA"


def test_match_registration_records_returns_empty_for_unknown_drug():
    assert agent_pipeline.match_registration_records("SomeUnknownDrugXYZ") == []


def test_match_registration_records_returns_empty_for_blank_drug():
    assert agent_pipeline.match_registration_records("") == []
    assert agent_pipeline.match_registration_records(None) == []


def test_match_submission_content_resolves_registrations_related_doc_ids():
    registration = agent_pipeline.match_registration_records("LUTATHERA", health_authority="FDA")
    submissions = agent_pipeline.match_submission_content(registration)

    assert len(submissions) == len(registration[0].related_submission_doc_ids)
    assert {s.doc_id for s in submissions} == set(registration[0].related_submission_doc_ids)


def test_match_submission_content_returns_empty_without_registration():
    assert agent_pipeline.match_submission_content([]) == []


def test_match_historic_precedents_matches_by_application_number():
    registration = agent_pipeline.match_registration_records(
        "Product tied to HIST-2015-NDA-198765-D04 precedent", health_authority="FDA"
    )
    precedents = agent_pipeline.match_historic_precedents(registration)

    assert len(precedents) == 1
    assert precedents[0].precedent_id == "HIST-2015-NDA-198765-D04"


def test_match_historic_precedents_returns_empty_when_no_precedent_for_application():
    registration = agent_pipeline.match_registration_records("LUTATHERA", health_authority="FDA")
    assert agent_pipeline.match_historic_precedents(registration) == []


def test_select_template_matches_region():
    fda = agent_pipeline._select_template("FDA")
    ema = agent_pipeline._select_template("EMA")
    unknown = agent_pipeline._select_template("Some Other Authority")

    assert fda["template_id"] == "TEMPLATE-FDA-DEFICIENCY-RESPONSE"
    assert ema["template_id"] == "TEMPLATE-EMA-LOQ-RESPONSE"
    assert unknown["template_id"] == "TEMPLATE-GENERIC-DOSSIER-RESPONSE"


@patch("app.services.agent_pipeline.call_tool")
def test_draft_response_includes_all_evidence_sources_and_region_terms(mock_call_tool):
    mock_call_tool.return_value = ({"text": "Draft response text.", "citations": ["REG-US-NDA-205930"]}, _USAGE)
    registration = agent_pipeline.match_registration_records("LUTATHERA", health_authority="FDA")
    submissions = agent_pipeline.match_submission_content(registration)
    precedents = agent_pipeline.match_historic_precedents(registration)

    draft, usage = agent_pipeline.draft_response(
        _sample_request(), registration, submissions, precedents, CorrespondenceMeta(source="FDA"), direction="Be concise."
    )

    assert draft.text == "Draft response text."
    assert draft.template_id == "TEMPLATE-FDA-DEFICIENCY-RESPONSE"
    assert usage is _USAGE
    kwargs = mock_call_tool.call_args.kwargs
    assert kwargs["tool_name"] == "draft_response"
    assert "Be concise." in kwargs["user_text"]
    assert "REG-US-NDA-205930" in kwargs["user_text"]
    assert "CDER" in kwargs["user_text"]
    assert "SUB-NDA-205930" in kwargs["user_text"]


@patch("app.services.agent_pipeline.call_tool")
def test_draft_response_handles_no_linked_evidence(mock_call_tool):
    mock_call_tool.return_value = ({"text": "Draft response text.", "citations": []}, _USAGE)

    draft, _usage = agent_pipeline.draft_response(
        _sample_request(), [], [], [], CorrespondenceMeta(source=None), direction=None
    )

    assert draft.text == "Draft response text."
    assert draft.template_id == "TEMPLATE-GENERIC-DOSSIER-RESPONSE"
    kwargs = mock_call_tool.call_args.kwargs
    assert '"linked_registration_records": []' in kwargs["user_text"]
    assert '"linked_submission_content": []' in kwargs["user_text"]
    assert '"linked_historic_precedents": []' in kwargs["user_text"]


def test_as_list_passes_through_native_list():
    assert agent_pipeline._as_list([{"a": 1}]) == [{"a": 1}]


def test_as_list_parses_well_formed_json_string():
    assert agent_pipeline._as_list('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_as_list_recovers_from_trailing_extra_data():
    # Reproduces the real failure: Bedrock tool-use serialized `requests` as a
    # JSON string, and the model appended stray content after a complete,
    # valid array -- json.loads raises JSONDecodeError("Extra data", ...).
    # raw_decode should recover the leading, complete array instead of
    # crashing the whole extraction.
    malformed = '[{"a": 1}, {"b": 2}]{"stray": "duplicate or junk content"}'
    assert agent_pipeline._as_list(malformed) == [{"a": 1}, {"b": 2}]


def test_as_list_raises_clear_error_for_genuinely_malformed_json():
    with pytest.raises(BedrockToolCallError):
        agent_pipeline._as_list('[{"a": 1}, {"unterminated": "str')


def test_as_list_returns_empty_for_blank_string():
    assert agent_pipeline._as_list("") == []
    assert agent_pipeline._as_list("   ") == []


def test_as_list_returns_empty_for_non_list_json():
    assert agent_pipeline._as_list('{"not": "a list"}') == []
