"""Thin client for invoking the link/draft agents on the Bedrock AgentCore
Runtime (data plane: bedrock-agentcore InvokeAgentRuntime).

Used by app.services.agent_runtime when AGENTCORE_RUNTIME_ARN is set (the
deployed topology): the FastAPI Lambda becomes a thin middle layer that
delegates the agentic steps to the managed runtime instead of running the
Strands agents in-process.
"""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Any, Dict

import boto3
from botocore.config import Config

from app.config import AGENTCORE_RUNTIME_ARN, AWS_REGION


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "bedrock-agentcore",
        region_name=AWS_REGION,
        config=Config(read_timeout=120, retries={"max_attempts": 2, "mode": "standard"}),
    )


def _session_id() -> str:
    # InvokeAgentRuntime requires runtimeSessionId to be >= 33 chars.
    return f"ha-{uuid.uuid4().hex}{uuid.uuid4().hex}"


def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the deployed AgentCore Runtime with a JSON payload and return the
    agent's JSON response as a dict."""
    response = _client().invoke_agent_runtime(
        agentRuntimeArn=AGENTCORE_RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=_session_id(),
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode("utf-8"),
    )
    return json.loads(response["response"].read())
