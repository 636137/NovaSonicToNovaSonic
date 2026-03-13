"""
AI Voice Tester for Amazon Connect

A comprehensive testing framework that makes real voice calls
to test Amazon Connect contact centers using AWS-native services.

Components:
- Amazon Chime SDK PSTN Audio for real phone calls
- Amazon Transcribe Streaming for speech-to-text
- Amazon Polly for text-to-speech
- Amazon Bedrock (Claude) for AI-powered responses
- AWS Lambda for serverless call handling
- Amazon DynamoDB for test state and results
- Amazon S3 for recordings

Usage:
    from voice_tester import VoiceTester
    
    tester = VoiceTester()
    result = tester.run_test('scenarios/census_survey.yaml', '+15551234567')
"""

__version__ = "1.0.0"
__author__ = "Voice Test Agent"

from voice_tester.config import Config, get_config, load_scenario
from voice_tester.cli import main as cli_main

__all__ = [
    'Config',
    'get_config', 
    'load_scenario',
    'cli_main',
]
