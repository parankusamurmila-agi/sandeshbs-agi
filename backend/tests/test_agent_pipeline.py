from unittest.mock import patch

from app.models import HaRequest, LinkedEvidence, SourceLocation
from app.services import agent_pipeline


def _sample_request() -> HaRequest:
    return HaRequest(
        request_id="1",
        section="Clinical and Statistical Comments",
        text="Submit the primary cleaned and verified data used to generate the CSR and TLFs.",
        referenced_items=["CSR", "TLFs"],
        source=SourceLocation(page=1, paragraph=11),
    )


@patch("app.services.agent_pipeline.call_tool")
def test_extract_letter_parses_meta_and_requests(mock_call_tool):
    mock_call_tool.return_value = {
        "meta": {"applicant": "Teva Pharmaceuticals", "product": "LUTATHERA", "letter_date": "2016", "source": "FDA"},
        "requests": [
            {
                "request_id": "1",
                "section": "Clinical and Statistical Comments",
                "text": "Submit the primary cleaned and verified data...",
                "referenced_items": ["CSR", "TLFs"],
                "source": {"page": 1, "paragraph": 11},
            }
        ],
    }

    meta, requests = agent_pipeline.extract_letter('<p page="1" idx="11">...</p>')

    assert meta.applicant == "Teva Pharmaceuticals"
    assert meta.product == "LUTATHERA"
    assert len(requests) == 1
    assert requests[0].request_id == "1"
    assert requests[0].source.page == 1

    kwargs = mock_call_tool.call_args.kwargs
    assert kwargs["tool_name"] == "extract_requests"


@patch("app.services.agent_pipeline.call_tool")
def test_link_evidence_only_accepts_candidates_from_catalog(mock_call_tool):
    catalog_doc_id = agent_pipeline._evidence_catalog()[0]["doc_id"]
    mock_call_tool.return_value = {
        "linked_evidence": [
            {
                "doc_id": catalog_doc_id,
                "title": "Some title",
                "doc_type": "CSR",
                "rationale": "Directly responsive to the CSR/TLF request.",
            }
        ]
    }

    linked = agent_pipeline.link_evidence(_sample_request())

    assert len(linked) == 1
    assert linked[0].doc_id == catalog_doc_id

    kwargs = mock_call_tool.call_args.kwargs
    assert kwargs["tool_name"] == "link_evidence"
    assert catalog_doc_id in kwargs["user_text"]


@patch("app.services.agent_pipeline.call_tool")
def test_draft_response_includes_evidence_detail_in_prompt(mock_call_tool):
    mock_call_tool.return_value = {"text": "Draft response text.", "citations": ["DOC-1"]}
    catalog_doc_id = agent_pipeline._evidence_catalog()[0]["doc_id"]
    evidence = [
        LinkedEvidence(doc_id=catalog_doc_id, title="t", doc_type="CSR", rationale="r"),
    ]

    draft = agent_pipeline.draft_response(_sample_request(), evidence, direction="Be concise.")

    assert draft.text == "Draft response text."
    assert draft.citations == ["DOC-1"]

    kwargs = mock_call_tool.call_args.kwargs
    assert kwargs["tool_name"] == "draft_response"
    assert "Be concise." in kwargs["user_text"]
    assert catalog_doc_id in kwargs["user_text"]
