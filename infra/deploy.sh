#!/usr/bin/env bash
# Zip-package deploy of the HA Request & Response Agent backend, with NO Docker
# and NO CDK/Node -- just Linux + pip + the AWS CLI. Intended to run in AWS
# CloudShell (or any Linux shell with AWS creds), because a correct Linux
# Lambda bundle can't be cross-built from Windows (pip evaluates the
# sys_platform marker against the host, so mcp -> pywin32 breaks the resolve).
#
# Usage (from the repo's infra/ directory):
#   bash deploy.sh
#
# Re-runnable: updates the stack in place on repeat runs.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="HaResponseAgentBackend"
MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-sonnet-5}"

cd "$(dirname "$0")"   # the infra/ directory, so ./build and ./template.yaml resolve

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STAGING_BUCKET="ha-deploy-staging-${ACCOUNT_ID}-${REGION}"

echo "== 1/4 Building Lambda bundle (python3.12 / linux wheels) =="
rm -rf build/lambda packaged.yaml
mkdir -p build/lambda
# Explicit target so the bundle matches the Lambda python3.12 runtime even if
# this shell's own python differs. On Linux the sys_platform marker resolves to
# "linux", so mcp's win32-only pywin32 dependency is correctly skipped.
python3 -m pip install \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --target build/lambda \
  -r ../backend/requirements-lambda.txt
cp -r ../backend/app build/lambda/app
# Trim bytecode caches to keep the package under Lambda's 250 MB unzipped limit.
find build/lambda -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
echo "   bundle size: $(du -sh build/lambda | cut -f1)"

echo "== 2/4 Ensuring staging bucket ${STAGING_BUCKET} =="
if ! aws s3api head-bucket --bucket "$STAGING_BUCKET" --region "$REGION" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$STAGING_BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$STAGING_BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
fi

echo "== 3/4 Packaging (zip + upload to S3, rewrite template) =="
aws cloudformation package \
  --template-file template.yaml \
  --s3-bucket "$STAGING_BUCKET" \
  --output-template-file packaged.yaml \
  --region "$REGION"

echo "== 4/4 Deploying stack ${STACK_NAME} =="
aws cloudformation deploy \
  --template-file packaged.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "BedrockModelId=${MODEL_ID}" \
  --region "$REGION"

echo "== Done. Stack outputs: =="
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs" \
  --output table
