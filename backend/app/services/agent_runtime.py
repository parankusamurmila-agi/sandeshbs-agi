"""Dispatch the two agentic steps (link, draft) to the right place:

- If AGENTCORE_RUNTIME_ARN is set (deployed topology), delegate to the managed
  Bedrock AgentCore Runtime via InvokeAgentRuntime -- the agents run on
  AgentCore, this process is just a middle layer.
- Otherwise (local dev, or inside the runtime container itself), run the
  Strands agents in-process via app.services.agent_pipeline.

The return shapes are identical in both cases, so the API routes don't care
which path ran. Keeping this dispatch OUT of agent_pipeline guarantees the
AgentCore entrypoint (agentcore_agent.py), which calls agent_pipeline
directly, always runs in-process and can never recurse into itself.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.config import AGENTCORE_RUNTIME_ARN
from app.models import (
    CorrespondenceMeta,
    Draft,
    HaRequest,
    HistoricPrecedent,
    RegistrationRecord,
    SubmissionDocument,
)
from app.services import agent_pipeline
from app.services.bedrock_client import UsageInfo


def _usage(data: dict) -> UsageInfo:
    return UsageInfo(
        model_id=data.get("model_id", ""),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        cache_read_input_tokens=data.get("cache_read_input_tokens", 0),
        cache_write_input_tokens=data.get("cache_write_input_tokens", 0),
    )


def link_request(
    drug: Optional[str], health_authority: Optional[str] = None
) -> Tuple[List[RegistrationRecord], List[SubmissionDocument], List[HistoricPrecedent], UsageInfo]:
    if not AGENTCORE_RUNTIME_ARN:
        return agent_pipeline.link_request(drug, health_authority)

    from app.services import agentcore_client

    out = agentcore_client.invoke(
        {"action": "link", "drug": drug, "health_authority": health_authority}
    )
    return (
        [RegistrationRecord.model_validate(r) for r in out.get("linked_registration", [])],
        [SubmissionDocument.model_validate(s) for s in out.get("linked_submissions", [])],
        [HistoricPrecedent.model_validate(p) for p in out.get("linked_precedents", [])],
        _usage(out.get("usage", {})),
    )


def draft_response(
    request: HaRequest,
    linked_registration: List[RegistrationRecord],
    linked_submissions: List[SubmissionDocument],
    linked_precedents: List[HistoricPrecedent],
    correspondence_meta: CorrespondenceMeta,
    direction: Optional[str] = None,
) -> Tuple[Draft, UsageInfo]:
    if not AGENTCORE_RUNTIME_ARN:
        return agent_pipeline.draft_response(
            request, linked_registration, linked_submissions, linked_precedents, correspondence_meta, direction
        )

    from app.services import agentcore_client

    out = agentcore_client.invoke(
        {
            "action": "draft",
            "question": {
                "request_id": request.request_id,
                "section": request.section,
                "drug": request.drug,
                "text": request.text,
                "source": request.source.model_dump(),
            },
            "linked_registration": [r.model_dump() for r in linked_registration],
            "linked_submissions": [s.model_dump() for s in linked_submissions],
            "linked_precedents": [p.model_dump() for p in linked_precedents],
            "correspondence_meta": correspondence_meta.model_dump(),
            "direction": direction,
        }
    )
    return Draft.model_validate(out["draft"]), _usage(out.get("usage", {}))
