# Amazon Connect Voice Testing Framework

Automated voice testing for Amazon Connect contact centers using AI-powered callers. Make real phone calls, interact with IVR systems, and validate conversation flows.

## Features

- **Real PSTN Voice Calls** - Actual phone calls via AWS Chime SDK SIP Media Application
- **AI-Powered Callers** - Lambda handlers with Polly TTS that talk to your contact flows
- **Status Tracking** - DynamoDB tracks call states in real-time
- **Nova Sonic Integration** - AI-to-AI voice conversations using Amazon Bedrock
- **Copilot Agent Skills** - Reusable AI skills for deployment, testing, and voice workflows

## Test Results

```
✅ Census Survey: received_input (12.5s)
✅ Treasury IVR: received_input (10.4s)
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Test Runner   │────▶│  Chime SDK PSTN  │────▶│ Amazon Connect  │
│ run_pstn_tests  │     │  SIP Media App   │     │  Contact Flow   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │   SIP Lambda     │
                        │  - Polly TTS     │
                        │  - Status Track  │
                        └──────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │    DynamoDB      │
                        │ voice-test-      │
                        │ scenarios        │
                        └──────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.12+ (required for AWS Smithy SDK)
- AWS Account with:
  - Amazon Connect instance
  - Chime SDK Voice resources
  - Bedrock access (for AI responses)
- AWS CLI configured

### Installation

```bash
# Clone the repository
git clone https://github.com/636137/NovaSonicToNovaSonic.git
cd NovaSonicToNovaSonic

# Create virtual environment
python3.12 -m venv .venv312
source .venv312/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run Voice Tests

```bash
# Run PSTN voice tests against Connect instances
python voice_tester/run_pstn_tests.py
```

### Run Nova Sonic Demo

```bash
# AI-to-AI voice conversation
python voice_tester/sonic_live_playback.py
```

## Project Structure

```
├── .github/
│   ├── copilot-instructions.md    # Copilot custom instructions
│   └── skills/                    # Agent Skills (copy these!)
│       ├── aws-deployment/        # AWS infrastructure deployment
│       ├── nova-sonic/            # Voice streaming with Bedrock
│       ├── testing-automation/    # Test generation
│       └── voice-testing/         # PSTN call testing
├── cdk/                           # CDK infrastructure stacks
├── contact_flows/                 # Connect flow JSON definitions
├── lambda/                        # Lambda function handlers
├── lex/                           # Lex bot definitions
├── scripts/                       # Utility scripts
│   ├── fix_sip_lambda.py         # Update SIP Lambda handler
│   └── setup_voice_testing.py    # Infrastructure setup
└── voice_tester/                  # Voice testing framework
    ├── run_pstn_tests.py         # Main test runner
    ├── sonic_live_playback.py    # Nova Sonic demo
    └── scenarios/                 # Test scenario YAML files
```

---

## Copilot Agent Skills

This project includes **four reusable Agent Skills** for GitHub Copilot. Copy the `.github/skills/` folder to your projects to enable AI-powered workflows.

### Available Skills

| Skill | Invoke With | Description |
|-------|-------------|-------------|
| AWS Deployment | `/aws-deployment` | Deploy Connect, Lex, Lambda with self-healing and error recovery |
| Nova Sonic | `/nova-sonic` | Bidirectional voice streaming with Amazon Bedrock |
| Voice Testing | `/voice-testing` | PSTN call tests against contact flows |
| Testing Automation | `/testing-automation` | Generate unit and integration tests |

### Quick Setup for Your Project

**Copy skills to your project:**

```bash
# Copy the entire skills folder
cp -r .github/skills/ /path/to/your/project/.github/skills/

# Copy the Copilot instructions
cp .github/copilot-instructions.md /path/to/your/project/.github/
```

**Use in Copilot Chat:**
1. Type `/` to see available skills
2. Select a skill or let Copilot auto-detect based on your query
3. Skills provide domain-specific knowledge and workflows

### Skills File Format

Skills use the [VS Code Agent Skills](https://agentskills.io) format:

```yaml
---
name: skill-name
description: Brief description of what the skill does
argument-hint: "[optional] [arguments]"
user-invocable: true
disable-model-invocation: false
---

# Skill Title

Detailed markdown content with:
- Instructions and guidelines
- Code examples
- Templates
- Troubleshooting tips
```

### Customizing Skills

Edit the SKILL.md files in each skill folder to customize behavior:

| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill definition and instructions |
| `examples/` | Code examples for common tasks |
| `templates/` | Reusable code/config templates |

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region | us-east-1 |
| `SIP_MEDIA_APP_ID` | Chime SIP Media Application ID | (auto-detected) |
| `FROM_PHONE` | Caller phone number | +13602098836 |
| `DYNAMODB_TABLE` | Test status tracking table | voice-test-scenarios |

### Test Scenarios

Create YAML scenarios in `voice_tester/scenarios/`:

```yaml
name: "My IVR Test"
description: "Test the main menu flow"

target:
  phone_number: "+15551234567"
  timeout_seconds: 120

steps:
  - action: "listen"
    expect:
      patterns: ["welcome", "main menu"]
  - action: "dtmf"
    content: "1"
  - action: "listen"
    expect:
      patterns: ["account balance"]
```

---

## AWS Resources Required

| Resource | Purpose |
|----------|---------|
| Chime SIP Media Application | Handles outbound PSTN calls |
| Chime Voice Connector | Routes calls to PSTN |
| Lambda (SIP Handler) | Processes SIP events, speaks via Polly |
| DynamoDB Table | Tracks test status and results |
| Phone Number | Caller ID for outbound calls |

### Infrastructure Setup

```bash
# Creates DynamoDB table and configures Lambda
python scripts/setup_voice_testing.py

# Update the SIP Lambda handler
python scripts/fix_sip_lambda.py
```

---

## Troubleshooting

### Call Timeouts

1. Verify DynamoDB table exists in correct region (us-east-1)
2. Check Lambda has DynamoDB permissions
3. View Lambda logs: `python scripts/check_lambda_logs.py`

### PlayAudio Errors

Use `Speak` action instead of `PlayAudio`:

```python
{
    "Type": "Speak",
    "Parameters": {
        "Text": "Hello, this is a test.",
        "Engine": "neural",
        "VoiceId": "Joanna"
    }
}
```

### Status Polling Issues

Test runner must poll by `transaction_id`:

```python
poll_id = result.transaction_id if result.transaction_id else result.test_id
```

---

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and test
4. Submit a pull request

---

*Built with Amazon Connect, Chime SDK, and Nova Sonic*
