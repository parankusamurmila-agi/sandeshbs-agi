"""Prompt storage: local JSON, Langfuse, or Amazon Bedrock Prompt Management.

The active source is `config.PROMPT_SOURCE` ("local" | "langfuse" | "bedrock").
When unset it stays backward-compatible: "langfuse" if the Langfuse keys are
set, else "local".

- local    -- read straight from app/data/prompts.json; edit it and the next
              request picks it up, no redeploy.
- langfuse -- fetch by name (label "production"); edit in Langfuse, no redeploy.
- bedrock  -- fetch from Bedrock Prompt Management by name (resolved to a prompt
              id via ListPrompts), reading `config.BEDROCK_PROMPT_VERSION`
              ("DRAFT" by default). The id map and resolved text are cached per
              process, so editing a prompt in Bedrock needs a restart (or a new
              deploy) to take effect -- this also keeps us well under Bedrock's
              low control-plane request rate. Push prompts up with
              `python -m scripts.seed_bedrock_prompts`.

prompts.json always backs every source as a fallback, so a missing/unreachable
remote prompt degrades to the bundled default rather than failing the request.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from app import config

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def _local_prompts() -> Dict[str, str]:
    return json.loads((DATA_DIR / "prompts.json").read_text(encoding="utf-8"))


def _resolve_source() -> str:
    if config.PROMPT_SOURCE in ("local", "langfuse", "bedrock"):
        return config.PROMPT_SOURCE
    if config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY:
        return "langfuse"
    return "local"


# --- Langfuse ---------------------------------------------------------------


@lru_cache(maxsize=1)
def _langfuse_client() -> Any:
    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.LANGFUSE_PUBLIC_KEY,
        secret_key=config.LANGFUSE_SECRET_KEY,
        host=config.LANGFUSE_HOST,
    )


def _langfuse_prompt(name: str, default: str) -> str:
    client = _langfuse_client()
    if client is None:
        return default
    try:
        return client.get_prompt(name, label="production", fallback=default).prompt
    except Exception:
        return default


# --- Bedrock Prompt Management ----------------------------------------------


@lru_cache(maxsize=1)
def _bedrock_agent_client() -> Any:
    import boto3

    return boto3.client("bedrock-agent", region_name=config.AWS_REGION)


@lru_cache(maxsize=1)
def _bedrock_prompt_ids() -> Dict[str, str]:
    """name -> prompt id, from a (paginated) ListPrompts call. Cached per
    process; a newly seeded prompt is picked up only after a restart."""
    client = _bedrock_agent_client()
    ids: Dict[str, str] = {}
    token: str | None = None
    while True:
        kwargs: Dict[str, Any] = {"maxResults": 100}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_prompts(**kwargs)
        for summary in resp.get("promptSummaries", []):
            ids.setdefault(summary["name"], summary["id"])
        token = resp.get("nextToken")
        if not token:
            return ids


def _variant_text(get_prompt_response: Dict[str, Any]) -> str:
    """Pull the TEXT template out of a GetPrompt response, preferring the
    prompt's defaultVariant and falling back to the first variant."""
    variants = get_prompt_response.get("variants") or []
    default_name = get_prompt_response.get("defaultVariant")
    chosen = next((v for v in variants if v.get("name") == default_name), None) or (
        variants[0] if variants else None
    )
    if not chosen:
        raise ValueError("Bedrock prompt has no variants")
    text = (chosen.get("templateConfiguration") or {}).get("text", {}).get("text")
    if not text:
        raise ValueError("Bedrock prompt variant has no TEXT template")
    return text


@lru_cache(maxsize=32)
def _bedrock_prompt_text(name: str, version: str) -> str:
    """Fetch and extract one prompt's text. Raises (so the caller falls back to
    the local default) if the prompt is unknown or has no text template.
    lru_cache does not cache exceptions, so a transient failure is retried."""
    prompt_id = _bedrock_prompt_ids().get(name)
    if not prompt_id:
        raise KeyError(f"no Bedrock prompt named {name!r}")
    kwargs: Dict[str, Any] = {"promptIdentifier": prompt_id}
    if version:  # omit for the DRAFT default; a numeric version pins that version
        kwargs["promptVersion"] = version
    return _variant_text(_bedrock_agent_client().get_prompt(**kwargs))


def _bedrock_prompt(name: str, default: str) -> str:
    try:
        return _bedrock_prompt_text(name, config.BEDROCK_PROMPT_VERSION)
    except Exception:
        return default


# --- public API -------------------------------------------------------------


def get_prompt(name: str) -> str:
    """Return a prompt's text by name from the active source
    (config.PROMPT_SOURCE), falling back to app/data/prompts.json."""
    default = _local_prompts()[name]
    source = _resolve_source()
    if source == "bedrock":
        return _bedrock_prompt(name, default)
    if source == "langfuse":
        return _langfuse_prompt(name, default)
    return default
