#!/usr/bin/env python3
"""
CDK App Entry Point for Voice Test Stack

Deploy with:
    cd voice_tester
    cdk deploy VoiceTestStack
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aws_cdk as cdk
from voice_tester.cdk.voice_test_stack import VoiceTestStack

app = cdk.App()

# Voice Test Stack
VoiceTestStack(
    app, 
    "VoiceTestStack",
    description="AI Voice Testing Agent for Amazon Connect",
    env=cdk.Environment(
        region="us-east-1"
    )
)

app.synth()
