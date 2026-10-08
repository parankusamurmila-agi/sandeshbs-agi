"""Thin wrapper around the Bedrock Converse API with forced tool-use.

Forcing the model to call a single tool whose input schema matches our
Pydantic model gives already-parsed, schema-conformant JSON back directly
from `toolUse.input` -- no prompt-text-schema + regex/repair layer needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config

from app.config import AWS_REGION, BEDROCK_MODEL_ID

_client = None

_NAME_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9 \-()\[\]]")
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _sanitize_document_name(name: str) -> str:
    """Bedrock Converse document blocks only allow alphanumerics, single
    spaces, hyphens, parentheses, and square brackets in `name` (no
    consecutive whitespace). Strip the extension, blank out anything else,
    then collapse whitespace runs to one space each."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    cleaned = _NAME_DISALLOWED_RE.sub(" ", stem)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    return cleaned or "HA Correspondence"


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=Config(
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    return _client


class BedrockToolCallError(RuntimeError):
    pass


@dataclass
class UsageInfo:
    """Token usage for one Converse call. Field names mirror Bedrock's own
    camelCase `usage` object (NOT the Anthropic-native Messages API's
    snake_case) -- total prompt size is
    input_tokens + cache_read_input_tokens + cache_write_input_tokens,
    since `inputTokens` only reports the non-cached remainder."""

    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0


# Approximate, per-million-token USD list pricing, keyed by a substring match
# on model_id. For demo/estimate purposes only -- NOT a billing-accurate
# figure (actual pricing depends on account/region/contract and may change).
# Cache ratios follow Anthropic's published cache pricing (write ~1.25x base
# input, read ~0.1x base input).
_PRICING_PER_MILLION_TOKENS: Dict[str, Dict[str, float]] = {
    "sonnet": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "opus": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "haiku": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
}
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30}


def estimate_cost_usd(usage: UsageInfo) -> float:
    """Rough cost estimate for one call, for display only -- see the pricing
    table's caveat above."""
    key = usage.model_id.lower()
    rates = next((r for name, r in _PRICING_PER_MILLION_TOKENS.items() if name in key), _DEFAULT_PRICING)
    return (
        usage.input_tokens * rates["input"]
        + usage.output_tokens * rates["output"]
        + usage.cache_write_input_tokens * rates["cache_write"]
        + usage.cache_read_input_tokens * rates["cache_read"]
    ) / 1_000_000


def call_tool(
    *,
    system_prompt: str,
    user_text: Optional[str] = None,
    document_bytes: Optional[bytes] = None,
    document_name: Optional[str] = None,
    document_format: str = "pdf",
    tool_name: str,
    tool_description: str,
    tool_schema: Dict[str, Any],
    max_tokens: int = 4096,
    model_id: Optional[str] = None,
    enable_prompt_cache: bool = True,
) -> Tuple[Dict[str, Any], UsageInfo]:
    """Runs one Converse call, forcing the model to call `tool_name`.

    Returns the tool's `input` dict (already validated against `tool_schema`
    by the model-side tool-use mechanism) plus token usage for the call. Pass
    `document_bytes` to attach a raw file (e.g. the HA letter PDF) instead
    of/alongside `user_text`.

    When `enable_prompt_cache` is true (default), the system prompt is marked
    as a cache checkpoint -- `system_prompt` is identical across every call
    for a given step (extract/draft), so caching it saves cost/latency on
    repeat invocations. If the system prompt is under the model's minimum
    cacheable token count, Bedrock silently skips caching (no error).
    """
    if user_text is None and document_bytes is None:
        raise ValueError("call_tool requires at least one of user_text or document_bytes")

    content: List[Dict[str, Any]] = []
    if document_bytes is not None:
        content.append(
            {
                "document": {
                    "format": document_format,
                    "name": _sanitize_document_name(document_name or "HA Correspondence"),
                    "source": {"bytes": document_bytes},
                }
            }
        )
    if user_text is not None:
        content.append({"text": user_text})

    system: List[Dict[str, Any]] = [{"text": system_prompt}]
    if enable_prompt_cache:
        system.append({"cachePoint": {"type": "default"}})

    resolved_model_id = model_id or BEDROCK_MODEL_ID
    client = _get_client()
    response = client.converse(
        modelId=resolved_model_id,
        system=system,
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": max_tokens},
        toolConfig={
            "tools": [
                {
                    "toolSpec": {
                        "name": tool_name,
                        "description": tool_description,
                        "inputSchema": {"json": tool_schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name}},
        },
    )

    usage_raw = response.get("usage") or {}
    usage = UsageInfo(
        model_id=resolved_model_id,
        input_tokens=usage_raw.get("inputTokens", 0),
        output_tokens=usage_raw.get("outputTokens", 0),
        cache_read_input_tokens=usage_raw.get("cacheReadInputTokens", 0),
        cache_write_input_tokens=usage_raw.get("cacheWriteInputTokens", 0),
    )

    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    for block in content_blocks:
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == tool_name:
            return tool_use["input"], usage

    raise BedrockToolCallError(
        f"Model did not return a toolUse block for '{tool_name}'. "
        f"stopReason={response.get('stopReason')}"
    )
