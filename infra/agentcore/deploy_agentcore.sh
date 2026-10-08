#!/usr/bin/env bash
# Deploy the link/draft agents to Bedrock AgentCore Runtime -- no local Docker
# (CodeBuild does the ARM64 build in the cloud) and no Node. Run in AWS
# CloudShell (or any Linux shell with AWS creds).
#
# Usage (from infra/agentcore/):
#   bash deploy_agentcore.sh
#
# Prints the runtime ARN at the end -- pass that to the backend deploy as
# AGENTCORE_RUNTIME_ARN so the API delegates link/draft to it.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
AGENT_NAME="ha_link_draft_agent"

cd "$(dirname "$0")"            # infra/agentcore/
REPO_ROOT="$(cd ../.. && pwd)"

echo "== 1/4 Assembling clean agent bundle =="
rm -rf build && mkdir -p build
cp "$REPO_ROOT/backend/agentcore_agent.py" build/agentcore_agent.py
cp "$REPO_ROOT/backend/requirements-agentcore.txt" build/requirements.txt
cp -r "$REPO_ROOT/backend/app" build/app
find build -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf build/app/.local_store 2>/dev/null || true

echo "== 2/4 Installing the AgentCore starter toolkit (pip, no Node) =="
python3 -m pip install --quiet --upgrade bedrock-agentcore-starter-toolkit

echo "== 3/4 Configuring (container build type -> CodeBuild, no local Docker) =="
cd build
export AGENTCORE_SUPPRESS_RECOMMENDATION=1
python3 -m bedrock_agentcore_starter_toolkit.cli.cli configure \
  -e agentcore_agent.py \
  -n "$AGENT_NAME" \
  -rf requirements.txt \
  -dt container \
  -r "$REGION" \
  -ni

echo "== 4/4 Launching (cloud CodeBuild build + deploy to AgentCore Runtime) =="
python3 -m bedrock_agentcore_starter_toolkit.cli.cli launch

echo
echo "== Done. Runtime ARN (use as AGENTCORE_RUNTIME_ARN for the backend): =="
python3 - <<'PY'
import yaml, glob, sys
cfgs = glob.glob(".bedrock_agentcore.yaml")
if not cfgs:
    sys.exit("no .bedrock_agentcore.yaml found")
data = yaml.safe_load(open(cfgs[0]))
# Structure varies by toolkit version; search for an agent runtime ARN.
import re, json
text = json.dumps(data)
m = re.search(r"arn:aws:bedrock-agentcore:[^\"]+runtime/[^\"/]+", text)
print(m.group(0) if m else "(ARN not found in config; see launch output above)")
PY
