from unittest.mock import MagicMock, patch

import pytest

from app.services import bedrock_client
from app.services.bedrock_client import UsageInfo


def test_sanitize_document_name_collapses_illegal_chars():
    assert bedrock_client._sanitize_document_name("2933_Intake001518.pdf") == "2933 Intake001518"
    assert bedrock_client._sanitize_document_name("a__b   c.pdf") == "a b c"


def test_sanitize_document_name_falls_back_when_empty():
    assert bedrock_client._sanitize_document_name("___.pdf") == "HA Correspondence"


def test_call_tool_requires_text_or_document():
    with pytest.raises(ValueError):
        bedrock_client.call_tool(
            system_prompt="sys",
            tool_name="t",
            tool_description="d",
            tool_schema={"type": "object"},
        )


def _converse_response(usage: dict | None = None) -> dict:
    return {
        "output": {"message": {"content": [{"toolUse": {"name": "extract_requests", "input": {"ok": True}}}]}},
        "stopReason": "tool_use",
        "usage": usage or {},
    }


@patch("app.services.bedrock_client._get_client")
def test_call_tool_builds_document_content_block(mock_get_client):
    mock_client = MagicMock()
    mock_client.converse.return_value = _converse_response()
    mock_get_client.return_value = mock_client

    bedrock_client.call_tool(
        system_prompt="sys",
        document_bytes=b"%PDF-1.4...",
        document_name="2933_Intake001518 (final).pdf",
        tool_name="extract_requests",
        tool_description="desc",
        tool_schema={"type": "object"},
    )

    content = mock_client.converse.call_args.kwargs["messages"][0]["content"]
    doc_block = next(b["document"] for b in content if "document" in b)
    assert doc_block["name"] == "2933 Intake001518 (final)"
    assert doc_block["format"] == "pdf"
    assert doc_block["source"]["bytes"] == b"%PDF-1.4..."


@patch("app.services.bedrock_client._get_client")
def test_call_tool_appends_cache_point_to_system_by_default(mock_get_client):
    mock_client = MagicMock()
    mock_client.converse.return_value = _converse_response()
    mock_get_client.return_value = mock_client

    bedrock_client.call_tool(
        system_prompt="sys",
        user_text="hello",
        tool_name="extract_requests",
        tool_description="desc",
        tool_schema={"type": "object"},
    )

    system = mock_client.converse.call_args.kwargs["system"]
    assert system == [{"text": "sys"}, {"cachePoint": {"type": "default"}}]


@patch("app.services.bedrock_client._get_client")
def test_call_tool_skips_cache_point_when_disabled(mock_get_client):
    mock_client = MagicMock()
    mock_client.converse.return_value = _converse_response()
    mock_get_client.return_value = mock_client

    bedrock_client.call_tool(
        system_prompt="sys",
        user_text="hello",
        tool_name="extract_requests",
        tool_description="desc",
        tool_schema={"type": "object"},
        enable_prompt_cache=False,
    )

    system = mock_client.converse.call_args.kwargs["system"]
    assert system == [{"text": "sys"}]


@patch("app.services.bedrock_client._get_client")
def test_call_tool_returns_usage_info(mock_get_client):
    mock_client = MagicMock()
    mock_client.converse.return_value = _converse_response(
        {"inputTokens": 120, "outputTokens": 40, "cacheReadInputTokens": 900, "cacheWriteInputTokens": 0}
    )
    mock_get_client.return_value = mock_client

    _, usage = bedrock_client.call_tool(
        system_prompt="sys",
        user_text="hello",
        tool_name="extract_requests",
        tool_description="desc",
        tool_schema={"type": "object"},
    )

    assert usage.input_tokens == 120
    assert usage.output_tokens == 40
    assert usage.cache_read_input_tokens == 900
    assert usage.cache_write_input_tokens == 0
    assert usage.model_id


def test_estimate_cost_usd_matches_known_model_substring():
    usage = UsageInfo(model_id="us.anthropic.claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert bedrock_client.estimate_cost_usd(usage) == pytest.approx(3.0 + 15.0)


def test_estimate_cost_usd_falls_back_for_unknown_model():
    usage = UsageInfo(model_id="some-unknown-model", input_tokens=1_000_000, output_tokens=0)
    assert bedrock_client.estimate_cost_usd(usage) > 0
