"""Runtime configuration, sourced from environment variables.

Values here are read once at import time so Lambda cold starts pay the cost
exactly once per container.
"""

import os

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
