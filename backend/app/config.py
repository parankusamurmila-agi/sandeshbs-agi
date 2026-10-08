"""Runtime configuration, sourced from environment variables.

Values here are read once at import time so Lambda cold starts pay the cost
exactly once per container.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Cross-region inference profile id for Claude Sonnet on Bedrock. Verify this
# against your account's enabled models with:
#   aws bedrock list-inference-profiles --region us-east-1
# and swap the value (or set BEDROCK_MODEL_ID) if your account exposes a
# different id/version.
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5")

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "HaCorrespondence")
S3_BUCKET = os.environ.get("S3_BUCKET", "ha-response-agent-local")

# When true, store.py keeps data in an in-process dict and skips S3/DynamoDB
# entirely -- used for local development without AWS resources provisioned.
LOCAL_STORE = os.environ.get("LOCAL_STORE", "false").lower() == "true"

# Where app.services.prompts reads prompts from: "local" (app/data/prompts.json),
# "langfuse", or "bedrock" (Amazon Bedrock Prompt Management). Leave unset for the
# backward-compatible default: "langfuse" when the Langfuse keys below are set,
# else "local". prompts.json always backs every source as a fallback.
PROMPT_SOURCE = os.environ.get("PROMPT_SOURCE", "").strip().lower()

# Bedrock Prompt Management version to read when PROMPT_SOURCE="bedrock": a
# published numeric version (e.g. "1") to pin, or "DRAFT" (default) for the
# latest edited copy. Prompt names are resolved to ids via ListPrompts.
BEDROCK_PROMPT_VERSION = os.environ.get("BEDROCK_PROMPT_VERSION", "DRAFT").strip()

# Optional: when both keys are set, app.services.prompts fetches prompts from
# Langfuse instead of its local defaults. See backend/.env.example.
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

# When set, the API's link/draft steps delegate to the deployed Bedrock
# AgentCore Runtime (InvokeAgentRuntime) instead of running the Strands agents
# in-process. Blank for local dev / inside the runtime itself (in-process).
AGENTCORE_RUNTIME_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN", "")

# Comma-separated CORS allow-list for the browser frontend. Defaults to the
# local Vite dev server; set to the deployed Amplify origin (or "*") in AWS.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]
