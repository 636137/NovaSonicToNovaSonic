# AI Voice Testing Agent for Amazon Connect (AWS-Native)

## Overview

A sophisticated AI-powered testing framework that tests Amazon Connect contact centers using **100% AWS services**. Supports two testing modes:

1. **WebRTC Mode** (Default): Direct connection to Connect - no phone number needed
2. **PSTN Mode**: Real phone calls via Amazon Chime SDK

The AI agent assumes the role of a caller, interacts with your IVR/Lex bot, and validates the experience.

## Quick Start (WebRTC Mode)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run setup wizard
python setup_webrtc.py

# 3. Run a test
python -m voice_tester test scenarios/census_survey_webrtc.yaml

# Or specify Connect IDs directly:
python -m voice_tester test scenarios/census_survey_webrtc.yaml \
    --instance-id YOUR_CONNECT_INSTANCE_ID \
    --contact-flow-id YOUR_CONTACT_FLOW_ID
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Test Scenario Definition                          │
│   YAML-based test cases defining personas, expected flows,          │
│   success criteria, and validation rules                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                     ┌──────────────┴──────────────┐
                     │                             │
                     ▼                             ▼
┌────────────────────────────┐   ┌────────────────────────────────────┐
│     WebRTC Mode            │   │          PSTN Mode                 │
│                            │   │                                    │
│  Direct Connect API        │   │  Amazon Chime SDK PSTN             │
│  - No phone number needed  │   │  - Real phone calls                │
│  - Chat + voice capable    │   │  - Requires provisioned number     │
│  - Instant connection      │   │  - Full audio recording            │
│  - Lower cost              │   │  - Most realistic testing          │
└────────────────────────────┘   └────────────────────────────────────┘
                     │                             │
                     └──────────────┬──────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Real-Time Voice Pipeline                          │
│                                                                      │
│    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐ │
│    │ Connect  │◄───►│ Amazon   │◄───►│ Amazon   │◄───►│ Amazon   │ │
│    │ WebRTC/  │     │Transcribe│     │ Bedrock  │     │  Polly   │ │
│    │  Chime   │     │Streaming │     │ (Claude) │     │  (TTS)   │ │
│    └──────────┘     └──────────┘     └──────────┘     └──────────┘ │
│                                                                      │
│    All AWS services - no third-party dependencies                   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 AI Caller Persona (Bedrock Claude)                   │
│   - Assumes different caller personalities                          │
│   - Follows test scenario scripts dynamically                       │
│   - Handles unexpected prompts intelligently                        │
│   - Provides realistic human-like responses                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Test Evaluation & Reporting                       │
│   - Validates expected conversation flow                            │
│   - Checks for proper intent recognition                            │
│   - Measures response latency                                        │
│   - Generates detailed test reports (S3/CloudWatch)                 │
│   - Records conversations for analysis                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Testing Modes Comparison

| Feature | WebRTC Mode | PSTN Mode |
|---------|-------------|-----------|
| Phone number required | No | Yes |
| Setup time | Instant | 1-2 days (Chime enablement) |
| Cost per test | ~$0.01 | ~$0.11 |
| Audio recording | Chat transcript | Full audio |
| Real phone experience | Chat/messaging | Actual voice call |
| Lex bot testing | Yes | Yes |
| Contact flow testing | Yes | Yes |

## AWS Services Used

| Service | Purpose |
|---------|---------|
| **Amazon Connect** | Contact center and WebRTC endpoint |
| **Amazon Chime SDK PSTN** | Real outbound phone calls (PSTN mode) |
| **Amazon Transcribe Streaming** | Real-time speech-to-text |
| **Amazon Polly** | Text-to-speech for AI responses |
| **Amazon Bedrock (Claude)** | AI brain for generating responses |
| **AWS Lambda** | Call event handling and orchestration |
| **Amazon DynamoDB** | Test state and results storage |
| **Amazon S3** | Call recordings and reports |
| **AWS CDK** | Infrastructure deployment |

## Key Features

### 1. Dual Testing Modes
- **WebRTC**: Direct API connection without phone infrastructure
- **PSTN**: Real phone calls for complete end-to-end testing
- Choose based on your testing requirements

### 2. AI-Powered Caller (Bedrock)
- Uses Amazon Bedrock (Claude) to generate contextual responses
- Follows test scenarios while handling unexpected situations
- Can assume different personas (confused caller, impatient caller, etc.)
- Sub-second response latency with streaming

### 3. Scenario-Based Testing
- Define test cases in YAML with expected flows
- Validate specific intents, slots, and responses
- Test happy paths and error handling

### 4. Comprehensive Reporting
- Pass/fail status for each test stored in DynamoDB
- Conversation transcripts from Transcribe
- Latency measurements via CloudWatch
- Audio recordings in S3 for manual review

## Supported Test Types

1. **Happy Path Tests** - Verify expected user journeys
2. **Edge Case Tests** - Test unusual inputs and error handling
3. **Load Tests** - Multiple concurrent callers
4. **Regression Tests** - Verify changes don't break existing flows
5. **Persona Tests** - Test with different caller behaviors

## Prerequisites

- AWS Account with appropriate permissions
- Amazon Chime SDK PSTN Audio enabled (requires AWS support ticket)
- A phone number provisioned in Chime SDK
- Target Amazon Connect phone number to test
- AWS credentials configured

## Quick Start

```bash
# 1. Deploy the infrastructure
cd voice_tester
cdk deploy VoiceTestStack

# 2. Provision a phone number (one-time)
python -m voice_tester.cli provision-number

# 3. Run the Census Survey test
python -m voice_tester.cli test scenarios/census_survey_happy_path.yaml \
    --target-number "+15551234567"

# 4. View results
python -m voice_tester.cli report --latest

# 5. List all test runs
python -m voice_tester.cli list-tests
```

## Project Structure

```
voice_tester/
├── __init__.py
├── cli.py                    # Command-line interface
├── orchestrator.py           # Test orchestration
├── cdk/
│   ├── __init__.py
│   └── voice_test_stack.py   # CDK infrastructure
├── lambda/
│   ├── call_handler/         # Chime SIP Media App handler
│   │   └── handler.py
│   ├── audio_processor/      # Real-time audio processing
│   │   └── handler.py
│   └── test_runner/          # Test execution logic
│       └── handler.py
├── ai_caller.py              # Bedrock AI persona engine
├── evaluator.py              # Test evaluation
├── reporter.py               # Report generation
├── config.py                 # Configuration
└── utils.py                  # Utilities

scenarios/
├── template.yaml             # Full schema documentation
├── census_survey_happy_path.yaml
├── census_survey_edge_cases.yaml
└── custom/                   # Your custom scenarios

```

## Creating Custom Test Scenarios

See `scenarios/template.yaml` for full schema documentation.

## Cost Estimates

Per test call (~2-3 minutes):
- Chime SDK PSTN: ~$0.004/min = ~$0.01
- Transcribe Streaming: ~$0.024/min = ~$0.07
- Polly: ~$4/1M chars = ~$0.01
- Bedrock Claude: ~$0.01-0.03
- Lambda/DynamoDB: ~$0.001
- **Total**: ~$0.10-0.15 per test call

## Security

- All data encrypted at rest (S3, DynamoDB)
- IAM roles with least privilege
- VPC endpoints available for private networking
- CloudTrail logging for audit
- No credentials stored - uses IAM roles

## Enabling Chime SDK PSTN Audio

Amazon Chime SDK PSTN Audio requires enablement:

1. Open AWS Support Center
2. Create a service limit increase request
3. Select "Chime SDK" as the service
4. Request "PSTN Audio" enablement
5. Typically approved within 1-2 business days

## License

**MAXIMUS PROPRIETARY** - Internal Use Only

This software is confidential and proprietary to Maximus Inc.
