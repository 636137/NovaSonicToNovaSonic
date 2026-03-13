#!/usr/bin/env python3
"""
Pure Nova Sonic AI-to-AI Conversation
Two Nova Sonic instances - no Polly needed.

Trick: Use text prompt to kick off customer's first turn, then route audio between them.
"""

import asyncio
import base64
import json
import os
import wave
import struct
import boto3

# AWS session
session = boto3.Session()
creds = session.get_credentials()
os.environ['AWS_ACCESS_KEY_ID'] = creds.access_key
os.environ['AWS_SECRET_ACCESS_KEY'] = creds.secret_key
if creds.token:
    os.environ['AWS_SESSION_TOKEN'] = creds.token

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

OUTPUT_RATE = 24000  # Nova produces 24kHz
INPUT_RATE = 16000   # Nova expects 16kHz

# Polly for bootstrap only
polly = boto3.client('polly', region_name='us-east-1')

def polly_audio(text: str, voice: str = "Ruth") -> bytes:
    """Generate 16kHz PCM from Polly."""
    resp = polly.synthesize_speech(Text=text, OutputFormat='pcm', VoiceId=voice, SampleRate='16000', Engine='neural')
    return resp['AudioStream'].read()


def resample_24k_to_16k(audio_24k: bytes) -> bytes:
    """Resample 24kHz audio to 16kHz."""
    samples = []
    for i in range(0, len(audio_24k) - 1, 2):
        samples.append(struct.unpack('<h', audio_24k[i:i+2])[0])
    
    # Take 2 out of every 3 samples
    resampled = []
    for i in range(0, len(samples), 3):
        resampled.append(samples[i])
        if i + 1 < len(samples):
            resampled.append(samples[i + 1])
    
    return b''.join(struct.pack('<h', s) for s in resampled)


class NovaSonicParticipant:
    """One Nova Sonic participant."""
    
    def __init__(self, name: str, voice_id: str, system_prompt: str):
        self.name = name
        self.voice_id = voice_id
        self.system_prompt = system_prompt
        self.stream = None
        self.prompt = "p1"
        self.content_num = 1
        self.audio_chunks = []
        self.current_text = ""
        self.all_texts = []
        self.all_audio = []
        
    async def send(self, data):
        await self.stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps(data).encode())
            )
        )
        
    async def connect(self):
        config = Config(
            endpoint_uri="https://bedrock-runtime.us-east-1.amazonaws.com",
            region="us-east-1",
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        client = BedrockRuntimeClient(config=config)
        self.stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id='amazon.nova-sonic-v1:0')
        )
        print(f"[{self.name}] Connected")
        
    async def setup_session(self):
        """Set up session with system prompt."""
        await self.send({"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024, "temperature": 0.8}}}})
        
        await self.send({"event": {"promptStart": {
            "promptName": self.prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": OUTPUT_RATE,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": self.voice_id,
                "encoding": "base64",
                "audioType": "SPEECH"
            }
        }}})
        
        # System prompt
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt,
            "contentName": "sys",
            "type": "TEXT",
            "interactive": False,
            "role": "SYSTEM",
            "textInputConfiguration": {"mediaType": "text/plain"}
        }}})
        await self.send({"event": {"textInput": {
            "promptName": self.prompt,
            "contentName": "sys",
            "content": self.system_prompt
        }}})
        await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": "sys"}}})
        
        print(f"[{self.name}] Session ready (voice: {self.voice_id})")
        
    async def send_text_prompt(self, text: str):
        """Send a text prompt to trigger speech output."""
        content_name = f"text{self.content_num}"
        
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt,
            "contentName": content_name,
            "type": "TEXT",
            "interactive": True,
            "role": "USER",
            "textInputConfiguration": {"mediaType": "text/plain"}
        }}})
        await self.send({"event": {"textInput": {
            "promptName": self.prompt,
            "contentName": content_name,
            "content": text
        }}})
        await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": content_name}}})
        self.content_num += 1
        
    async def start_audio_input(self):
        """Start audio input turn."""
        content_name = f"audio{self.content_num}"
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt,
            "contentName": content_name,
            "type": "AUDIO",
            "interactive": True,
            "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": INPUT_RATE,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64"
            }
        }}})
        
    async def send_audio(self, audio_16k: bytes):
        """Send audio chunk."""
        content_name = f"audio{self.content_num}"
        await self.send({"event": {"audioInput": {
            "promptName": self.prompt,
            "contentName": content_name,
            "content": base64.b64encode(audio_16k).decode()
        }}})
        
    async def end_audio_input(self):
        """End audio input turn."""
        content_name = f"audio{self.content_num}"
        await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": content_name}}})
        self.content_num += 1
        
    async def receive_response(self, timeout_seconds: float = 20.0) -> bytes:
        """Receive audio response."""
        self.audio_chunks = []
        self.current_text = ""
        
        start = asyncio.get_event_loop().time()
        got_audio = False
        silence_count = 0
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout_seconds:
                print(f"[{self.name}] Timeout")
                break
                
            try:
                output = await asyncio.wait_for(self.stream.await_output(), timeout=0.5)
                result = await output[1].receive()
                
                if result.value and result.value.bytes_:
                    data = json.loads(result.value.bytes_.decode())
                    
                    if 'event' in data:
                        evt = data['event']
                        
                        if 'textOutput' in evt:
                            text = evt['textOutput'].get('content', '')
                            role = evt['textOutput'].get('role', '')
                            if role == 'ASSISTANT':
                                # Filter out interrupted markers
                                text = text.replace('{ "interrupted" : true }', '').strip()
                                if text:
                                    self.current_text += text
                                
                        elif 'audioOutput' in evt:
                            audio = base64.b64decode(evt['audioOutput']['content'])
                            self.audio_chunks.append(audio)
                            got_audio = True
                            silence_count = 0
                            
                        elif 'contentEnd' in evt:
                            # Check if it's assistant content ending
                            if got_audio:
                                break
                                
            except asyncio.TimeoutError:
                if got_audio:
                    silence_count += 1
                    if silence_count > 3:  # 1.5 seconds silence after audio
                        break
                continue
            except Exception as e:
                if "closed" not in str(e).lower():
                    print(f"[{self.name}] Error: {e}")
                break
        
        if self.current_text:
            self.all_texts.append(self.current_text)
            
        audio_out = b''.join(self.audio_chunks)
        if audio_out:
            self.all_audio.append(audio_out)
        return audio_out
        
    async def cleanup(self):
        try:
            await self.send({"event": {"promptEnd": {"promptName": self.prompt}}})
            await self.send({"event": {"sessionEnd": {}}})
        except:
            pass


def save_wav(audio: bytes, filename: str, rate: int):
    """Save to WAV file."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio)
    print(f"Saved: {filename}")


async def run_conversation():
    customer_system = """You are Sarah, a customer calling about a suspicious charge.

SITUATION: You noticed $47.99 from "STREAMTECH SERVICES" on your statement and don't recognize it.

BEHAVIOR:
- Speak naturally like a real phone caller
- Express mild concern about the charge
- Answer questions the agent asks (your name is Sarah Miller)
- If they explain it's a streaming service, try to recall if you signed up
- Keep responses SHORT - 1-2 sentences maximum
- End call politely when issue is resolved"""

    agent_system = """You are Alex, a customer service rep at ABC Bank.

ROLE:
- Greet warmly, ask how you can help
- Listen to customer's concern
- The $47.99 from STREAMTECH SERVICES is their StreamTech Plus subscription (set up 3 months ago)
- Verify customer identity if needed (ask for name)
- Explain the charge clearly
- Offer to block the merchant if they want to cancel
- Keep responses SHORT - 1-2 sentences maximum
- Be warm and helpful"""

    print("=" * 60)
    print("🎭 NOVA SONIC vs NOVA SONIC CONVERSATION")
    print("=" * 60)
    print("Customer (Sarah/Tiffany) <---> Agent (Alex/Matthew)")
    print("Note: Turn 1 uses Polly to bootstrap, then pure Sonic-to-Sonic")
    print("-" * 60)
    
    customer = NovaSonicParticipant("CUSTOMER", "tiffany", customer_system)
    agent = NovaSonicParticipant("AGENT", "matthew", agent_system)
    
    await customer.connect()
    await agent.connect()
    
    await customer.setup_session()
    await agent.setup_session()
    
    try:
        print("\n" + "=" * 60)
        print("CONVERSATION START")
        print("=" * 60)
        
        # TURN 1: Bootstrap with Polly "hello" sent to AGENT, agent responds
        # Then customer Nova Sonic hears agent and takes over
        print("\n--- Turn 1: Customer calls in (Polly bootstrap) ---")
        
        # Generate customer's opening with Polly
        opening = "Hi, I'm calling about a charge on my statement. I see forty-seven ninety-nine from something called StreamTech Services, and I don't recognize it at all."
        bootstrap_audio = polly_audio(opening, "Ruth")
        print(f"🔵 CUSTOMER [Polly]: {opening}")
        
        # Send to AGENT's Nova Sonic
        await agent.start_audio_input()
        chunk_size = 640
        for i in range(0, len(bootstrap_audio), chunk_size):
            await agent.send_audio(bootstrap_audio[i:i+chunk_size])
            await asyncio.sleep(0.02)
        
        # Silence for VAD
        silence = b'\x00' * 640
        for _ in range(100):  # 2 seconds
            await agent.send_audio(silence)
            await asyncio.sleep(0.02)
        await agent.end_audio_input()
        
        # Now AGENT (Nova Sonic) responds
        print("\n--- Turn 2: Agent responds (Nova Sonic) ---")
        agent_audio = await agent.receive_response(timeout_seconds=15.0)
        
        if agent_audio:
            print(f"\n🟢 AGENT: {agent.current_text}")
            
            # From here, CUSTOMER Nova Sonic hears agent and responds
            print("\n--- Turn 3: Customer responds (Nova Sonic) ---")
            agent_audio_16k = resample_24k_to_16k(agent_audio)
            
            await customer.start_audio_input()
            for i in range(0, len(agent_audio_16k), chunk_size):
                await customer.send_audio(agent_audio_16k[i:i+chunk_size])
                await asyncio.sleep(0.02)
            for _ in range(100):  # 2 seconds silence
                await customer.send_audio(silence)
                await asyncio.sleep(0.02)
            await customer.end_audio_input()
            
            customer_audio = await customer.receive_response(timeout_seconds=15.0)
            
            if customer_audio:
                print(f"\n🔵 CUSTOMER: {customer.current_text}")
                
                # Turn 4: Agent responds
                print("\n--- Turn 4: Agent responds (Nova Sonic) ---")
                customer_audio_16k = resample_24k_to_16k(customer_audio)
                
                await agent.start_audio_input()
                for i in range(0, len(customer_audio_16k), chunk_size):
                    await agent.send_audio(customer_audio_16k[i:i+chunk_size])
                    await asyncio.sleep(0.02)
                for _ in range(100):
                    await agent.send_audio(silence)
                    await asyncio.sleep(0.02)
                await agent.end_audio_input()
                
                agent_audio_2 = await agent.receive_response(timeout_seconds=15.0)
                
                if agent_audio_2:
                    print(f"\n🟢 AGENT: {agent.current_text}")
                    
                    # Turn 5: Customer responds
                    print("\n--- Turn 5: Customer responds (Nova Sonic) ---")
                    agent_audio_16k_2 = resample_24k_to_16k(agent_audio_2)
                    
                    await customer.start_audio_input()
                    for i in range(0, len(agent_audio_16k_2), chunk_size):
                        await customer.send_audio(agent_audio_16k_2[i:i+chunk_size])
                        await asyncio.sleep(0.02)
                    for _ in range(100):
                        await customer.send_audio(silence)
                        await asyncio.sleep(0.02)
                    await customer.end_audio_input()
                    
                    customer_audio_2 = await customer.receive_response(timeout_seconds=15.0)
                    
                    if customer_audio_2:
                        print(f"\n🔵 CUSTOMER: {customer.current_text}")
                        
                        # Turn 6: Final agent response
                        print("\n--- Turn 6: Agent responds (Nova Sonic) ---")
                        customer_audio_16k_2 = resample_24k_to_16k(customer_audio_2)
                        
                        await agent.start_audio_input()
                        for i in range(0, len(customer_audio_16k_2), chunk_size):
                            await agent.send_audio(customer_audio_16k_2[i:i+chunk_size])
                            await asyncio.sleep(0.02)
                        for _ in range(100):
                            await agent.send_audio(silence)
                            await asyncio.sleep(0.02)
                        await agent.end_audio_input()
                        
                        agent_audio_3 = await agent.receive_response(timeout_seconds=15.0)
                        
                        if agent_audio_3:
                            print(f"\n🟢 AGENT: {agent.current_text}")
        
        print("\n" + "=" * 60)
        print("CONVERSATION END")
        print("=" * 60)
        
    finally:
        await customer.cleanup()
        await agent.cleanup()
    
    # Save audio
    print("\n" + "=" * 60)
    print("SAVING AUDIO FILES")
    print("=" * 60)
    
    if customer.all_audio:
        combined = b''.join(customer.all_audio)
        save_wav(combined, "voice_output/sonic_customer.wav", OUTPUT_RATE)
        
    if agent.all_audio:
        combined = b''.join(agent.all_audio)
        save_wav(combined, "voice_output/sonic_agent.wav", OUTPUT_RATE)
    
    # Print transcript
    print("\n" + "=" * 60)
    print("FULL TRANSCRIPT")
    print("=" * 60)
    print("\n🔵 CUSTOMER said:")
    for i, t in enumerate(customer.all_texts, 1):
        print(f"  [{i}] {t}")
    print("\n🟢 AGENT said:")
    for i, t in enumerate(agent.all_texts, 1):
        print(f"  [{i}] {t}")


if __name__ == "__main__":
    asyncio.run(run_conversation())
