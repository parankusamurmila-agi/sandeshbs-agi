#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.backend_stack import BackendStack

app = cdk.App()

# Deploy in us-east-1: the "us.anthropic.*" Bedrock cross-region inference
# profiles route from this region, and it keeps the Lambda's auto-provided
# AWS_REGION env var aligned with the model id without us having to (and
# being unable to, since AWS_REGION is a reserved Lambda env var) override it.
BackendStack(
    app,
    "HaResponseAgentBackend",
    env=cdk.Environment(region="us-east-1"),
)

app.synth()
