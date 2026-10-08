"""Bedrock AgentCore Runtime entrypoint for the agentic link + draft steps.

Hosts the two genuinely-agentic steps of the pipeline on the managed AgentCore
Runtime. The same Strands agents that run in-process locally
(app.services.agent_pipeline) run here unchanged -- this module is only a thin
request router + (de)serialization layer around them.

The runtime passes the invoke payload through unchanged; we route on
`payload["action"]`:

  {"action": "link", "drug": "...", "health_authority": "FDA"}
    -> {"linked_registration": [...], "linked_submissions": [...],
        "linked_precedents": [...], "usage": {...}}

  {"action": "draft", "question": {request_id, section, drug, text, source},
   "linked_registration": [...], "linked_submissions": [...],
   "linked_precedents": [...], "correspondence_meta": {...},
   "direction": "..."}
    -> {"draft": {text, citations, template_id}, "usage": {...}}

Run locally for a smoke test with `python agentcore_agent.py` (starts the
runtime's dev HTTP server); deploy with the agentcore CLI (see
infra/agentcore/).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from bedrock_agentcore import BedrockAgentCoreApp

from app.models import (
    CorrespondenceMeta,
    HaRequest,
    HistoricPrecedent,
    RegistrationRecord,
    SubmissionDocument,
)
from app.services import agent_pipeline

app = BedrockAgentCoreApp()


def _link(payload: Dict[str, Any]) -> Dict[str, Any]:
    registrations, submissions, precedents, usage = agent_pipeline.link_request(
        payload.get("drug"), payload.get("health_authority")
    )
    return {
        "linked_registration": [r.model_dump() for r in registrations],
        "linked_submissions": [s.model_dump() for s in submissions],
        "linked_precedents": [p.model_dump() for p in precedents],
        "usage": asdict(usage),
    }


def _draft(payload: Dict[str, Any]) -> Dict[str, Any]:
    request = HaRequest.model_validate(payload["question"])
    draft, usage = agent_pipeline.draft_response(
        request,
        [RegistrationRecord.model_validate(r) for r in payload.get("linked_registration", [])],
        [SubmissionDocument.model_validate(s) for s in payload.get("linked_submissions", [])],
        [HistoricPrecedent.model_validate(p) for p in payload.get("linked_precedents", [])],
        CorrespondenceMeta.model_validate(payload.get("correspondence_meta") or {}),
        payload.get("direction"),
    )
    return {"draft": draft.model_dump(), "usage": asdict(usage)}


_ACTIONS = {"link": _link, "draft": _draft}


@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = (payload or {}).get("action")
    handler = _ACTIONS.get(action)
    if handler is None:
        return {"error": f"unknown action {action!r}; expected one of {sorted(_ACTIONS)}"}
    return handler(payload)


if __name__ == "__main__":
    app.run()
