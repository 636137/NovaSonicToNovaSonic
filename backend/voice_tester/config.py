"""
AI Voice Tester Configuration (AWS-Native)

Handles loading and validating configuration from environment and files.
Uses only AWS services: Chime SDK, Transcribe, Polly, Bedrock, Lambda, DynamoDB, S3
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class ChimeConfig:
    """Amazon Chime SDK PSTN configuration"""
    phone_number: str = ""  # Chime SDK phone number for outbound calls
    sip_media_application_id: str = ""
    voice_connector_id: str = ""
    region: str = "us-east-1"
    
    def validate(self) -> List[str]:
        errors = []
        if not self.phone_number:
            errors.append("CHIME_PHONE_NUMBER is required (provision via CLI or console)")
        return errors


@dataclass
class BedrockConfig:
    """Amazon Bedrock configuration for AI responses"""
    model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"
    region: str = "us-east-1"
    temperature: float = 0.7
    max_tokens: int = 150
    
    def validate(self) -> List[str]:
        # Bedrock uses IAM roles, no API keys needed
        return []


@dataclass
class TranscribeConfig:
    """Amazon Transcribe Streaming configuration"""
    language_code: str = "en-US"
    media_sample_rate_hz: int = 8000  # PSTN audio is 8kHz
    media_encoding: str = "pcm"
    vocabulary_name: Optional[str] = None  # Custom vocabulary for domain terms
    region: str = "us-east-1"
    
    def validate(self) -> List[str]:
        return []


@dataclass
class PollyConfig:
    """Amazon Polly configuration for TTS"""
    voice_id: str = "Joanna"
    engine: str = "neural"  # standard, neural
    language_code: str = "en-US"
    output_format: str = "pcm"
    sample_rate: str = "8000"  # Match PSTN
    region: str = "us-east-1"
    
    def validate(self) -> List[str]:
        return []


@dataclass
class NovaSonicConfig:
    """Amazon Nova Sonic configuration for unified STT/TTS"""
    model_id: str = "amazon.nova-sonic-v1:0"
    voice_id: str = "tiffany"  # tiffany, matthew, amy
    region: str = "us-east-1"
    sample_rate: int = 16000  # 16kHz for WebRTC
    audio_format: str = "pcm"
    enabled: bool = True  # Use Nova Sonic instead of Transcribe/Polly
    
    def validate(self) -> List[str]:
        return []


@dataclass
class StorageConfig:
    """S3 and DynamoDB configuration"""
    recordings_bucket: str = ""
    reports_bucket: str = ""
    test_results_table: str = ""
    region: str = "us-east-1"
    
    def validate(self) -> List[str]:
        # These will be created by CDK if not specified
        return []


@dataclass
class LambdaConfig:
    """Lambda function ARNs (set after deployment)"""
    call_handler_arn: str = ""
    audio_processor_arn: str = ""
    test_runner_arn: str = ""
    webrtc_tester_arn: str = ""
    nova_sonic_processor_arn: str = ""
    
    def validate(self) -> List[str]:
        return []


@dataclass
class ConnectConfig:
    """Amazon Connect configuration for WebRTC testing"""
    instance_id: str = ""
    contact_flow_id: str = ""
    queue_id: str = ""
    region: str = "us-east-1"
    
    def validate(self) -> List[str]:
        errors = []
        if not self.instance_id:
            errors.append("CONNECT_INSTANCE_ID is required for WebRTC testing")
        return errors


@dataclass 
class Config:
    """Main configuration container - AWS-native"""
    chime: ChimeConfig = field(default_factory=ChimeConfig)
    bedrock: BedrockConfig = field(default_factory=BedrockConfig)
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    polly: PollyConfig = field(default_factory=PollyConfig)
    nova_sonic: NovaSonicConfig = field(default_factory=NovaSonicConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    lambdas: LambdaConfig = field(default_factory=LambdaConfig)
    connect: ConnectConfig = field(default_factory=ConnectConfig)
    
    # AWS general
    aws_region: str = "us-east-1"
    aws_profile: Optional[str] = None
    
    # Testing mode: 'webrtc' or 'pstn'
    test_mode: str = "webrtc"
    
    # Local paths
    scenarios_dir: Path = field(default_factory=lambda: Path("scenarios"))
    
    # Logging
    log_level: str = "INFO"
    
    def validate(self) -> List[str]:
        """Validate all configuration"""
        errors = []
        errors.extend(self.chime.validate())
        errors.extend(self.bedrock.validate())
        errors.extend(self.transcribe.validate())
        errors.extend(self.polly.validate())
        return errors
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Load configuration from environment variables"""
        region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        
        return cls(
            chime=ChimeConfig(
                phone_number=os.getenv("CHIME_PHONE_NUMBER", ""),
                sip_media_application_id=os.getenv("CHIME_SIP_MEDIA_APP_ID", ""),
                voice_connector_id=os.getenv("CHIME_VOICE_CONNECTOR_ID", ""),
                region=region,
            ),
            bedrock=BedrockConfig(
                model_id=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"),
                region=region,
                temperature=float(os.getenv("BEDROCK_TEMPERATURE", "0.7")),
                max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "150")),
            ),
            transcribe=TranscribeConfig(
                language_code=os.getenv("TRANSCRIBE_LANGUAGE", "en-US"),
                media_sample_rate_hz=int(os.getenv("TRANSCRIBE_SAMPLE_RATE", "8000")),
                vocabulary_name=os.getenv("TRANSCRIBE_VOCABULARY"),
                region=region,
            ),
            polly=PollyConfig(
                voice_id=os.getenv("POLLY_VOICE_ID", "Joanna"),
                engine=os.getenv("POLLY_ENGINE", "neural"),
                language_code=os.getenv("POLLY_LANGUAGE", "en-US"),
                region=region,
            ),
            nova_sonic=NovaSonicConfig(
                model_id=os.getenv("NOVA_SONIC_MODEL_ID", "amazon.nova-sonic-v1:0"),
                voice_id=os.getenv("NOVA_SONIC_VOICE", "tiffany"),
                region=region,
                sample_rate=int(os.getenv("NOVA_SONIC_SAMPLE_RATE", "16000")),
                enabled=os.getenv("NOVA_SONIC_ENABLED", "true").lower() in ("true", "1", "yes"),
            ),
            storage=StorageConfig(
                recordings_bucket=os.getenv("RECORDINGS_BUCKET", ""),
                reports_bucket=os.getenv("REPORTS_BUCKET", ""),
                test_results_table=os.getenv("TEST_RESULTS_TABLE", ""),
                region=region,
            ),
            lambdas=LambdaConfig(
                call_handler_arn=os.getenv("CALL_HANDLER_LAMBDA_ARN", ""),
                audio_processor_arn=os.getenv("AUDIO_PROCESSOR_LAMBDA_ARN", ""),
                test_runner_arn=os.getenv("TEST_RUNNER_LAMBDA_ARN", ""),
                webrtc_tester_arn=os.getenv("WEBRTC_TESTER_ARN", ""),
                nova_sonic_processor_arn=os.getenv("NOVA_SONIC_PROCESSOR_ARN", ""),
            ),
            connect=ConnectConfig(
                instance_id=os.getenv("CONNECT_INSTANCE_ID", ""),
                contact_flow_id=os.getenv("CONTACT_FLOW_ID", ""),
                queue_id=os.getenv("CONNECT_QUEUE_ID", ""),
                region=region,
            ),
            aws_region=region,
            aws_profile=os.getenv("AWS_PROFILE"),
            test_mode=os.getenv("TEST_MODE", "webrtc"),
            scenarios_dir=Path(os.getenv("SCENARIOS_DIR", "scenarios")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
    
    @classmethod
    def from_cdk_outputs(cls, outputs: Dict[str, str]) -> 'Config':
        """Load configuration from CDK stack outputs"""
        config = cls.from_env()
        
        # Override with CDK outputs
        if 'ChimePhoneNumber' in outputs:
            config.chime.phone_number = outputs['ChimePhoneNumber']
        if 'SipMediaApplicationId' in outputs:
            config.chime.sip_media_application_id = outputs['SipMediaApplicationId']
        if 'RecordingsBucket' in outputs:
            config.storage.recordings_bucket = outputs['RecordingsBucket']
        if 'TestResultsTable' in outputs:
            config.storage.test_results_table = outputs['TestResultsTable']
        if 'CallHandlerArn' in outputs:
            config.lambdas.call_handler_arn = outputs['CallHandlerArn']
        if 'AudioProcessorArn' in outputs:
            config.lambdas.audio_processor_arn = outputs['AudioProcessorArn']
        if 'TestRunnerArn' in outputs:
            config.lambdas.test_runner_arn = outputs['TestRunnerArn']
            
        return config


def load_scenario(path: Path) -> Dict[str, Any]:
    """Load a test scenario from YAML file"""
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def validate_scenario(scenario: Dict[str, Any]) -> List[str]:
    """Validate scenario structure"""
    errors = []
    
    # Required fields for all scenarios
    if 'name' not in scenario:
        errors.append("Scenario missing required field: name")
    
    if 'steps' not in scenario:
        errors.append("Scenario missing required field: steps")
    
    # Check connection mode - WebRTC or PSTN
    connection = scenario.get('connection', {})
    mode = connection.get('mode', 'webrtc')
    
    if mode == 'pstn':
        # PSTN mode requires phone number
        if 'target' not in scenario and 'phone_number' not in scenario.get('target', {}):
            errors.append("PSTN mode requires target.phone_number")
    # WebRTC mode doesn't require phone number
    
    if 'steps' in scenario:
        if not isinstance(scenario['steps'], list):
            errors.append("Scenario steps must be a list")
        elif len(scenario['steps']) == 0:
            errors.append("Scenario must have at least one step")
        else:
            for i, step in enumerate(scenario['steps']):
                if 'id' not in step:
                    errors.append(f"Step {i} missing id")
                if 'action' not in step:
                    errors.append(f"Step {i} missing action")
    
    return errors


# Singleton config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create config singleton"""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def set_config(config: Config) -> None:
    """Set config singleton (for testing)"""
    global _config
    _config = config
