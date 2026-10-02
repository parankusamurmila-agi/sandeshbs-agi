"""Thin wrapper around the Bedrock Converse API with forced tool-use.

Forcing the model to call a single tool whose input schema matches our
Pydantic model gives already-parsed, schema-conformant JSON back directly
from `toolUse.input` -- no prompt-text-schema + regex/repair layer needed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import boto3
from botocore.config import Config

from app.config import AWS_REGION, BEDROCK_MODEL_ID

_client = None


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


def call_tool(
    *,
    system_prompt: str,
    user_text: str,
    tool_name: str,
    tool_description: str,
    tool_schema: Dict[str, Any],
    max_tokens: int = 4096,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Runs one Converse call, forcing the model to call `tool_name`.

    Returns the tool's `input` dict, already validated against `tool_schema`
    by the model-side tool-use mechanism.
    """
    client = _get_client()
    response = client.converse(
        modelId=model_id or BEDROCK_MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_text}]}],
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

    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    for block in content_blocks:
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == tool_name:
            return tool_use["input"]

    raise BedrockToolCallError(
        f"Model did not return a toolUse block for '{tool_name}'. "
        f"stopReason={response.get('stopReason')}"
    )
