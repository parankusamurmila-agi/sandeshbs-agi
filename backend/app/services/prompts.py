"""Prompt storage: local JSON by default, Langfuse when credentials are set.

Locally (no Langfuse creds) prompts are read straight from
app/data/prompts.json -- edit that file and the next request picks it up,
no redeploy. In AWS, once LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY are set as
Lambda environment variables, prompts are fetched from Langfuse by name
(label "production") instead, so they can be edited there without a
redeploy either. The JSON file still backs every fetch as a fallback if
Langfuse is unreachable or the prompt is missing there.
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


@lru_cache(maxsize=1)
def _client() -> Any:
    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.LANGFUSE_PUBLIC_KEY,
        secret_key=config.LANGFUSE_SECRET_KEY,
        host=config.LANGFUSE_HOST,
    )


def get_prompt(name: str) -> str:
    """Return a prompt's text by name, preferring Langfuse over the local JSON file."""
    default = _local_prompts()[name]
    client = _client()
    if client is None:
        return default
    try:
        return client.get_prompt(name, label="production", fallback=default).prompt
    except Exception:
        return default
