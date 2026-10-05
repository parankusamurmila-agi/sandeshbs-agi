import os
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"


class BackendStack(Stack):
    """S3 (PDFs) + DynamoDB (correspondence records) + Lambda (FastAPI container) + HTTP API."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        pdf_bucket = s3.Bucket(
            self,
            "PdfBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        table = dynamodb.Table(
            self,
            "CorrespondenceTable",
            table_name="HaCorrespondence",
            partition_key=dynamodb.Attribute(name="correspondence_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        fn = lambda_.DockerImageFunction(
            self,
            "ApiFunction",
            code=lambda_.DockerImageCode.from_image_asset(str(BACKEND_DIR)),
            memory_size=1024,
            timeout=Duration.seconds(60),
            environment={
                "DYNAMODB_TABLE": table.table_name,
                "S3_BUCKET": pdf_bucket.bucket_name,
                "BEDROCK_MODEL_ID": self.node.try_get_context("bedrock_model_id") or "us.anthropic.claude-sonnet-5",
                # Read from the deployer's shell env at `cdk deploy` time (not committed
                # anywhere) so prompts come from Langfuse in AWS once these are set --
                # same prompts.json fallback applies if they're left blank.
                "LANGFUSE_PUBLIC_KEY": os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
                "LANGFUSE_SECRET_KEY": os.environ.get("LANGFUSE_SECRET_KEY", ""),
                "LANGFUSE_HOST": os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            },
        )

        table.grant_read_write_data(fn)
        pdf_bucket.grant_read_write(fn)

        # Hackathon-scoped: broad Bedrock invoke permission rather than enumerating every
        # foundation-model/inference-profile ARN. Tighten the Resource before production use.
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse", "bedrock:ConverseStream"],
                resources=["*"],
            )
        )

        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["http://localhost:5173"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["*"],
            ),
        )
        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=apigwv2_integrations.HttpLambdaIntegration("ApiIntegration", fn),
        )

        CfnOutput(self, "ApiUrl", value=http_api.url or "")
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "BucketName", value=pdf_bucket.bucket_name)
