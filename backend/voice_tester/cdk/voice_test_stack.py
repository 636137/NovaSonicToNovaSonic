"""
Voice Test Stack - CDK Infrastructure

Deploys all AWS resources needed for the AI Voice Testing Agent:
- Amazon Chime SDK SIP Media Application
- Lambda functions for call handling
- DynamoDB for test results
- S3 for recordings
- IAM roles with least privilege
"""
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_logs as logs,
)
from constructs import Construct
import os


class VoiceTestStack(Stack):
    """CDK Stack for AI Voice Testing Agent"""
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # =================================================================
        # S3 Buckets
        # =================================================================
        
        # Recordings bucket
        self.recordings_bucket = s3.Bucket(
            self, "RecordingsBucket",
            bucket_name=f"voice-test-recordings-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    expiration=Duration.days(90),  # Keep recordings 90 days
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INTELLIGENT_TIERING,
                            transition_after=Duration.days(30)
                        )
                    ]
                )
            ]
        )
        
        # Reports bucket
        self.reports_bucket = s3.Bucket(
            self, "ReportsBucket",
            bucket_name=f"voice-test-reports-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )
        
        # =================================================================
        # DynamoDB Tables
        # =================================================================
        
        # Test results table
        self.test_results_table = dynamodb.Table(
            self, "TestResultsTable",
            table_name="VoiceTestResults",
            partition_key=dynamodb.Attribute(
                name="test_id",
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
        
        # Add GSI for querying by scenario
        self.test_results_table.add_global_secondary_index(
            index_name="ScenarioIndex",
            partition_key=dynamodb.Attribute(
                name="scenario_name",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING
            ),
        )
        
        # Call state table (for active calls)
        self.call_state_table = dynamodb.Table(
            self, "CallStateTable",
            table_name="VoiceTestCallState",
            partition_key=dynamodb.Attribute(
                name="call_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # Temporary data
            time_to_live_attribute="ttl",
        )
        
        # =================================================================
        # IAM Roles
        # =================================================================
        
        # Lambda execution role with all needed permissions
        self.lambda_role = iam.Role(
            self, "VoiceTestLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        
        # Chime SDK permissions
        self.lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "chime:CreateSipMediaApplication",
                "chime:CreateSipMediaApplicationCall",
                "chime:UpdateSipMediaApplication",
                "chime:DeleteSipMediaApplication",
                "chime:GetSipMediaApplication",
                "chime:ListSipMediaApplications",
                "chime:CreatePhoneNumberOrder",
                "chime:GetPhoneNumberOrder",
                "chime:ListPhoneNumbers",
                "chime:GetPhoneNumber",
                "chime:UpdatePhoneNumber",
                "chime:DeletePhoneNumber",
                "chime:CreateVoiceConnector",
                "chime:GetVoiceConnector",
                "chime:UpdateSipMediaApplicationCall",
            ],
            resources=["*"]
        ))
        
        # Transcribe Streaming permissions
        self.lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "transcribe:StartStreamTranscription",
                "transcribe:StartStreamTranscriptionWebSocket",
            ],
            resources=["*"]
        ))
        
        # Polly permissions
        self.lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "polly:SynthesizeSpeech",
            ],
            resources=["*"]
        ))
        
        # Bedrock permissions (Claude + Nova Sonic)
        self.lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                # Amazon Nova Sonic for speech-to-speech
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-sonic-v1:0",
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-sonic*",
                f"arn:aws:bedrock:{self.region}::foundation-model/*",
            ]
        ))
        
        # Amazon Connect permissions (for WebRTC)
        self.lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "connect:StartWebRTCContact",
                "connect:StartChatContact",
                "connect:StartOutboundVoiceContact",
                "connect:StopContact",
                "connect:GetContactAttributes",
                "connect:UpdateContactAttributes",
                "connect:DescribeContact",
                "connect:ListContactFlows",
                "connect:DescribeContactFlow",
                "connect:ListQueues",
                "connect:DescribeQueue",
                "connect:ListInstances",
                "connect:DescribeInstance",
            ],
            resources=["*"]
        ))
        
        # Amazon Connect Participant permissions (for WebRTC signaling)
        self.lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "connectparticipant:CreateParticipantConnection",
                "connectparticipant:GetTranscript",
                "connectparticipant:SendEvent",
                "connectparticipant:SendMessage",
                "connectparticipant:DisconnectParticipant",
                "connectparticipant:GetAttachment",
                "connectparticipant:StartAttachmentUpload",
                "connectparticipant:CompleteAttachmentUpload",
            ],
            resources=["*"]
        ))
        
        # S3 permissions
        self.recordings_bucket.grant_read_write(self.lambda_role)
        self.reports_bucket.grant_read_write(self.lambda_role)
        
        # DynamoDB permissions
        self.test_results_table.grant_read_write_data(self.lambda_role)
        self.call_state_table.grant_read_write_data(self.lambda_role)
        
        # =================================================================
        # Lambda Functions
        # =================================================================
        
        # Shared Lambda layer for common dependencies
        # (In production, create a layer with boto3, etc.)
        
        # Call Handler - Handles Chime SIP Media Application events
        self.call_handler = lambda_.Function(
            self, "CallHandlerFunction",
            function_name="VoiceTest-CallHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/call_handler"),
            role=self.lambda_role,
            timeout=Duration.minutes(15),  # Long timeout for call duration
            memory_size=512,
            environment={
                "RECORDINGS_BUCKET": self.recordings_bucket.bucket_name,
                "CALL_STATE_TABLE": self.call_state_table.table_name,
                "TEST_RESULTS_TABLE": self.test_results_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        
        # Audio Processor - Handles real-time audio with Transcribe/Polly
        self.audio_processor = lambda_.Function(
            self, "AudioProcessorFunction",
            function_name="VoiceTest-AudioProcessor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/audio_processor"),
            role=self.lambda_role,
            timeout=Duration.minutes(15),
            memory_size=1024,  # More memory for audio processing
            environment={
                "RECORDINGS_BUCKET": self.recordings_bucket.bucket_name,
                "CALL_STATE_TABLE": self.call_state_table.table_name,
                "POLLY_VOICE_ID": "Joanna",
                "POLLY_ENGINE": "neural",
                "TRANSCRIBE_LANGUAGE": "en-US",
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        
        # Test Runner - Orchestrates test execution
        self.test_runner = lambda_.Function(
            self, "TestRunnerFunction",
            function_name="VoiceTest-TestRunner",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/test_runner"),
            role=self.lambda_role,
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "CALL_HANDLER_ARN": "",  # Will be set after creation
                "CALL_STATE_TABLE": self.call_state_table.table_name,
                "TEST_RESULTS_TABLE": self.test_results_table.table_name,
                "RECORDINGS_BUCKET": self.recordings_bucket.bucket_name,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        
        # AI Responder - Generates AI responses via Bedrock
        self.ai_responder = lambda_.Function(
            self, "AIResponderFunction",
            function_name="VoiceTest-AIResponder",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/ai_responder"),
            role=self.lambda_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "BEDROCK_MODEL_ID": "anthropic.claude-3-sonnet-20240229-v1:0",
                "CALL_STATE_TABLE": self.call_state_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        
        # WebRTC Tester - Direct WebRTC connection to Amazon Connect
        self.webrtc_tester = lambda_.Function(
            self, "WebRTCTesterFunction",
            function_name="VoiceTest-WebRTCTester",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="webrtc_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/webrtc_tester"),
            role=self.lambda_role,
            timeout=Duration.minutes(15),  # Long timeout for call duration
            memory_size=1024,
            environment={
                "CONNECT_INSTANCE_ID": "",  # Set via parameter or after deployment
                "CONTACT_FLOW_ID": "",  # Set via parameter or after deployment
                "BEDROCK_MODEL_ID": "anthropic.claude-3-sonnet-20240229-v1:0",
                "POLLY_VOICE_ID": "Joanna",
                "POLLY_ENGINE": "neural",
                "TRANSCRIBE_LANGUAGE": "en-US",
                "CALL_STATE_TABLE": self.call_state_table.table_name,
                "TEST_RESULTS_TABLE": self.test_results_table.table_name,
                "RECORDINGS_BUCKET": self.recordings_bucket.bucket_name,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        
        # Nova Sonic Voice Processor - Unified STT/TTS using Amazon Nova Sonic
        self.nova_sonic_processor = lambda_.Function(
            self, "NovaSonicProcessorFunction",
            function_name="VoiceTest-NovaSonicProcessor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="nova_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/nova_sonic"),
            role=self.lambda_role,
            timeout=Duration.minutes(5),  # Speech operations
            memory_size=1024,  # More memory for audio processing
            environment={
                "NOVA_SONIC_MODEL_ID": "amazon.nova-sonic-v1:0",
                "NOVA_SONIC_VOICE": "tiffany",  # Natural female voice
                "CALL_STATE_TABLE": self.call_state_table.table_name,
                "TEST_RESULTS_TABLE": self.test_results_table.table_name,
                "RECORDINGS_BUCKET": self.recordings_bucket.bucket_name,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        
        # =================================================================
        # Lambda invoke permissions (for internal calls)
        # =================================================================
        
        self.audio_processor.grant_invoke(self.call_handler)
        self.ai_responder.grant_invoke(self.audio_processor)
        self.call_handler.grant_invoke(self.test_runner)
        self.nova_sonic_processor.grant_invoke(self.call_handler)
        self.nova_sonic_processor.grant_invoke(self.webrtc_tester)
        
        # =================================================================
        # Outputs
        # =================================================================
        
        CfnOutput(self, "RecordingsBucketName",
            value=self.recordings_bucket.bucket_name,
            description="S3 bucket for call recordings",
            export_name="VoiceTestRecordingsBucket"
        )
        
        CfnOutput(self, "ReportsBucketName",
            value=self.reports_bucket.bucket_name,
            description="S3 bucket for test reports",
            export_name="VoiceTestReportsBucket"
        )
        
        CfnOutput(self, "TestResultsTableName",
            value=self.test_results_table.table_name,
            description="DynamoDB table for test results",
            export_name="VoiceTestResultsTable"
        )
        
        CfnOutput(self, "CallStateTableName",
            value=self.call_state_table.table_name,
            description="DynamoDB table for call state",
            export_name="VoiceTestCallStateTable"
        )
        
        CfnOutput(self, "CallHandlerArn",
            value=self.call_handler.function_arn,
            description="Call handler Lambda ARN",
            export_name="VoiceTestCallHandlerArn"
        )
        
        CfnOutput(self, "AudioProcessorArn",
            value=self.audio_processor.function_arn,
            description="Audio processor Lambda ARN",
            export_name="VoiceTestAudioProcessorArn"
        )
        
        CfnOutput(self, "TestRunnerArn",
            value=self.test_runner.function_arn,
            description="Test runner Lambda ARN",
            export_name="VoiceTestRunnerArn"
        )
        
        CfnOutput(self, "AIResponderArn",
            value=self.ai_responder.function_arn,
            description="AI responder Lambda ARN",
            export_name="VoiceTestAIResponderArn"
        )
        
        CfnOutput(self, "WebRTCTesterArn",
            value=self.webrtc_tester.function_arn,
            description="WebRTC tester Lambda ARN",
            export_name="VoiceTestWebRTCTesterArn"
        )
        
        CfnOutput(self, "NovaSonicProcessorArn",
            value=self.nova_sonic_processor.function_arn,
            description="Nova Sonic voice processor Lambda ARN",
            export_name="VoiceTestNovaSonicProcessorArn"
        )
