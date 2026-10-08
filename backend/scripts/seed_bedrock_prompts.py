"""Push the default prompts into Amazon Bedrock Prompt Management.

Mirrors seed_langfuse_prompts: upserts every prompt in app/data/prompts.json
by name (create on first run, update the DRAFT thereafter) and publishes an
immutable numbered version each run. Needs AWS creds with bedrock:ListPrompts,
CreatePrompt, UpdatePrompt, and CreatePromptVersion in AWS_REGION. Safe to
re-run. The app reads these when PROMPT_SOURCE=bedrock (reading DRAFT by
default; set BEDROCK_PROMPT_VERSION to pin a published version).

    cd backend && python -m scripts.seed_bedrock_prompts
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import boto3

from app import config
from app.services.prompts import _local_prompts

_VARIANT_NAME = "default"
_DESCRIPTION = "HA Request & Response Agent system prompt"


def _iter_prompt_summaries(client: Any) -> Iterator[Dict[str, Any]]:
    token = None
    while True:
        kwargs: Dict[str, Any] = {"maxResults": 100}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_prompts(**kwargs)
        yield from resp.get("promptSummaries", [])
        token = resp.get("nextToken")
        if not token:
            return


def main() -> None:
    client = boto3.client("bedrock-agent", region_name=config.AWS_REGION)
    existing = {s["name"]: s["id"] for s in _iter_prompt_summaries(client)}

    for name, text in _local_prompts().items():
        variant = {
            "name": _VARIANT_NAME,
            "templateType": "TEXT",
            "templateConfiguration": {"text": {"text": text}},
            # Informational only -- these prompts are used as system prompts via
            # Converse/Strands, not executed through Bedrock's native prompt
            # runner, so modelId just records the intended model in the console.
            "modelId": config.BEDROCK_MODEL_ID,
        }
        if name in existing:
            prompt_id = existing[name]
            client.update_prompt(
                promptIdentifier=prompt_id,
                name=name,
                description=_DESCRIPTION,
                defaultVariant=_VARIANT_NAME,
                variants=[variant],
            )
            action = "updated"
        else:
            created = client.create_prompt(
                name=name,
                description=_DESCRIPTION,
                defaultVariant=_VARIANT_NAME,
                variants=[variant],
            )
            prompt_id = created["id"]
            action = "created"

        version = client.create_prompt_version(promptIdentifier=prompt_id)["version"]
        print(f"{action} {name} (id={prompt_id}) -> published version {version}")


if __name__ == "__main__":
    main()
