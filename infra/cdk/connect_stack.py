from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_s3 as s3,
    aws_logs as logs,
    custom_resources as cr,
)
from constructs import Construct
import json


class ConnectCensusStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB table for survey responses
        survey_table = dynamodb.Table(
            self, "CensusSurveyResponses",
            partition_key=dynamodb.Attribute(
                name="contact_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # S3 bucket for call recordings and chat transcripts
        recordings_bucket = s3.Bucket(
            self, "CensusRecordingsBucket",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # Lambda execution role
        lambda_role = iam.Role(
            self, "CensusLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )

        # Grant DynamoDB permissions
        survey_table.grant_read_write_data(lambda_role)

        # Lambda function for survey logic
        survey_lambda = lambda_.Function(
            self, "CensusSurveyFunction",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="survey_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/survey"),
            role=lambda_role,
            timeout=Duration.seconds(30),
            environment={
                "SURVEY_TABLE": survey_table.table_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Lambda function for Lex fulfillment
        lex_lambda = lambda_.Function(
            self, "CensusLexFulfillment",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="lex_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/lex"),
            role=lambda_role,
            timeout=Duration.seconds(30),
            environment={
                "SURVEY_TABLE": survey_table.table_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Create IAM role for Amazon Connect
        connect_role = iam.Role(
            self, "ConnectServiceRole",
            assumed_by=iam.ServicePrincipal("connect.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonConnect_FullAccess"
                )
            ]
        )

        # Grant Connect access to S3 bucket
        recordings_bucket.grant_read_write(connect_role)

        # Grant Connect permission to invoke Lambda
        survey_lambda.grant_invoke(iam.ServicePrincipal("connect.amazonaws.com"))
        lex_lambda.grant_invoke(iam.ServicePrincipal("lex.amazonaws.com"))

        # Create Lex bot role
        lex_role = iam.Role(
            self, "LexBotRole",
            assumed_by=iam.ServicePrincipal("lexv2.amazonaws.com"),
        )

        lex_lambda.grant_invoke(lex_role)

        # Custom resource to create Amazon Connect instance
        connect_policy = iam.Policy(
            self, "ConnectCustomResourcePolicy",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "connect:CreateInstance",
                        "connect:DescribeInstance",
                        "connect:DeleteInstance",
                        "connect:ListInstances",
                        "connect:UpdateInstanceAttribute",
                        "ds:CreateAlias",
                        "ds:DeleteDirectory",
                        "ds:DescribeDirectories",
                        "ds:CreateIdentityPoolDirectory",
                        "iam:CreateServiceLinkedRole",
                        "iam:AttachRolePolicy",
                        "iam:PutRolePolicy",
                    ],
                    resources=["*"]
                )
            ]
        )

        connect_custom_resource_role = iam.Role(
            self, "ConnectCustomResourceRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        connect_custom_resource_role.attach_inline_policy(connect_policy)

        # Note: Amazon Connect instance creation via CDK requires manual setup
        # or CloudFormation custom resources. For simplicity, we'll output
        # instructions and provide a script to create it.

        # Outputs
        CfnOutput(self, "SurveyTableName", value=survey_table.table_name)
        CfnOutput(self, "RecordingsBucketName", value=recordings_bucket.bucket_name)
        CfnOutput(self, "SurveyLambdaArn", value=survey_lambda.function_arn)
        CfnOutput(self, "LexLambdaArn", value=lex_lambda.function_arn)
        CfnOutput(self, "LexRoleArn", value=lex_role.role_arn)
        CfnOutput(
            self, "ConnectInstructions",
            value="Run ./scripts/create_connect_instance.py to create the Connect instance"
        )
