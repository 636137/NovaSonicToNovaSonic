# Nova Sonic to Nova Sonic 🎭

**Two AI voices having a real conversation** - using Amazon Nova Sonic bidirectional streaming.

https://github.com/user-attachments/assets/placeholder

## What This Is

This project demonstrates **pure AI-to-AI voice conversation** using Amazon Nova Sonic:

- **Customer AI** (Sarah, female voice): Calling about a suspicious $47.99 charge
- **Agent AI** (Alex, male voice): Customer service representative helping resolve the issue

Both AIs are completely autonomous Nova Sonic instances - they listen to each other and respond naturally.

## 🎧 Hear It

Run the demo and hear two AIs talk:

```bash
# Record conversation, then play it back
python voice_tester/sonic_live_playback.py
```

## 🚀 Quick Start

### Requirements

- **Python 3.12+** (required for AWS Smithy SDK)
- **AWS Account** with Nova Sonic access enabled in Bedrock
- **macOS/Linux** with audio output

### Setup

```bash
# 1. Create Python 3.12 virtual environment
python3.12 -m venv .venv312
source .venv312/bin/activate

# 2. Install dependencies
pip install boto3 sounddevice numpy
pip install aws-sdk-bedrock-runtime

# 3. Configure AWS credentials
aws configure
# Or set environment variables:
# export AWS_ACCESS_KEY_ID=...
# export AWS_SECRET_ACCESS_KEY=...

# 4. Run the demo!
python voice_tester/sonic_live_playback.py
```

## 📁 Key Files

| File | Description |
|------|-------------|
| `voice_tester/sonic_live_playback.py` | Main demo - records conversation, plays back |
| `voice_tester/sonic_to_sonic.py` | Basic AI-to-AI conversation |
| `voice_tester/nova_sonic_live.py` | Live microphone conversation with Nova Sonic |

## 🔧 Technical Details

### How It Works

1. **Bootstrap**: Customer's opening line uses Polly TTS (one sentence to start)
2. **Agent Responds**: Nova Sonic (Matthew voice) hears customer, generates response
3. **Customer Responds**: Nova Sonic (Tiffany voice) hears agent, responds
4. **Loop**: Audio routes between two Nova Sonic instances

```
Customer Nova Sonic  ←→  Agent Nova Sonic
   (Tiffany voice)         (Matthew voice)
```

### Audio Specs

- **Input**: 16kHz, 16-bit, mono PCM
- **Output**: 24kHz, 16-bit, mono PCM
- Resampling handled automatically when routing between instances

### Available Voices

| Voice | Gender | Accent |
|-------|--------|--------|
| matthew | Male | US English |
| tiffany | Female | US English |
| amy | Female | UK English |

### Key Discovery: VAD

Nova Sonic uses Voice Activity Detection (VAD). You must send ~2 seconds of silence after speech for the AI to recognize the turn is complete.

## 📝 Sample Conversation

```
============================================================
🎭 AI-to-AI CONVERSATION
============================================================
Customer (Sarah/Tiffany) <---> Agent (Alex/Matthew)

--- Turn 1: Customer calls in ---
🔵 CUSTOMER: Hi, I'm calling about a charge on my statement. 
I see forty-seven ninety-nine from StreamTech Services...

--- Turn 2: Agent responds ---
🟢 AGENT: Hi there! I'd be happy to help. The $47.99 is your 
StreamTech Plus subscription from three months ago.

--- Turn 3: Customer responds ---
🔵 CUSTOMER: Oh, I don't recall signing up for that.

--- Turn 4: Agent responds ---
🟢 AGENT: I understand. May I verify your identity first?

--- Turn 5: Customer responds ---
🔵 CUSTOMER: Can you help me cancel it?

--- Turn 6: Agent responds ---
🟢 AGENT: Absolutely! I can block the merchant if you'd like.
```

## 🔐 AWS Setup

1. **Enable Nova Sonic** in [Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. **Model**: `amazon.nova-sonic-v1:0`
3. **Region**: us-east-1 (or your preferred region)

## 📄 License

MIT

---

*Built with Amazon Nova Sonic - the first truly bidirectional voice AI on AWS.*
