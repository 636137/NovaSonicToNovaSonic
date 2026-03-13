#!/usr/bin/env python3
"""
Nova Sonic AI-to-AI Conversation
Two Nova Sonic instances talking to each other:
- Customer (voice: Ruth) calling with a problem
- Agent (voice: Matthew) helping resolve it
"""

import asyncio
import base64
import json
import os
import wave
import struct
import boto3

# AWS credentials
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

OUTPUT_RATE = 24000
INPUT_RATE = 16000  # Nova expects 16kHz input

class NovaSonicParticipant:
    """One participant in the conversation (either customer or agent)."""
    
    def __init__(self, name: str, voice_id: str, system_prompt: str):
        self.name = name
        self.voice_id = voice_id
        self.system_prompt = system_prompt
        self.stream = None
        self.prompt = "p1"
        self.done = False
        self.audio_out_queue = asyncio.Queue()  # Audio we generate
        self.audio_in_queue = asyncio.Queue()   # Audio we receive from other
        self.texts = []
        self.all_audio = []  # Store all audio for saving
        
    async def send(self, data):
        await self.stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps(data).encode())
            )
        )
        
    async def connect(self):
        """Connect to Nova Sonic."""
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
        """Setup the Nova Sonic session."""
        # Session start
        await self.send({"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024, "temperature": 0.8}}}})
        
        # Prompt start with audio config
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
        
        # Audio input config
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt,
            "contentName": "audio1",
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
        print(f"[{self.name}] Session ready (voice: {self.voice_id})")
        
    async def receive_responses(self):
        """Receive responses and queue audio output."""
        try:
            while not self.done:
                try:
                    output = await asyncio.wait_for(self.stream.await_output(), timeout=1.0)
                    result = await output[1].receive()
                    if result.value and result.value.bytes_:
                        data = json.loads(result.value.bytes_.decode())
                        if 'event' in data:
                            evt = data['event']
                            if 'textOutput' in evt:
                                text = evt['textOutput']['content']
                                role = evt['textOutput'].get('role', '')
                                if role == 'ASSISTANT' and 'interrupted' not in text:
                                    self.texts.append(text)
                                    print(f"\n[{self.name}]: {text}")
                            elif 'audioOutput' in evt:
                                audio = base64.b64decode(evt['audioOutput']['content'])
                                self.all_audio.append(audio)
                                await self.audio_out_queue.put(audio)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if "closed" not in str(e).lower():
                        print(f"[{self.name}] RX Error: {e}")
                    break
        except asyncio.CancelledError:
            pass
            
    async def send_audio_from_queue(self):
        """Send audio from input queue to Nova Sonic."""
        try:
            while not self.done:
                try:
                    # Get audio from other participant
                    audio = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
                    # Resample from 24kHz to 16kHz for input
                    # Simple decimation (take every 1.5th sample approximated)
                    audio_array = []
                    audio_bytes = audio
                    for i in range(0, len(audio_bytes) - 1, 2):
                        audio_array.append(struct.unpack('<h', audio_bytes[i:i+2])[0])
                    
                    # Resample 24kHz -> 16kHz (take 2 out of every 3 samples)
                    resampled = []
                    for i in range(0, len(audio_array), 3):
                        resampled.append(audio_array[i])
                        if i + 1 < len(audio_array):
                            resampled.append(audio_array[i + 1])
                    
                    resampled_bytes = b''.join(struct.pack('<h', s) for s in resampled)
                    
                    await self.send({"event": {"audioInput": {
                        "promptName": self.prompt,
                        "contentName": "audio1",
                        "content": base64.b64encode(resampled_bytes).decode()
                    }}})
                except asyncio.TimeoutError:
                    # Send a bit of silence to keep connection alive
                    silence = b'\x00' * 640
                    await self.send({"event": {"audioInput": {
                        "promptName": self.prompt,
                        "contentName": "audio1",
                        "content": base64.b64encode(silence).decode()
                    }}})
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass
            
    async def cleanup(self):
        """End session cleanly."""
        try:
            await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": "audio1"}}})
            await self.send({"event": {"promptEnd": {"promptName": self.prompt}}})
            await self.send({"event": {"sessionEnd": {}}})
        except:
            pass


class AItoAIConversation:
    """Orchestrate conversation between two Nova Sonic instances."""
    
    def __init__(self):
        # Customer calling with a problem - female voice
        self.customer = NovaSonicParticipant(
            name="CUSTOMER",
            voice_id="tiffany",  # Female voice (US)
            system_prompt="""You are Sarah, a customer calling a bank's customer service line. 
You're calling because you noticed a suspicious charge of $47.99 on your account from "AMZN Digital" 
that you don't recognize. You're a bit worried but polite. 

Start by greeting the agent and explaining your concern about the charge.
Keep your responses natural and conversational - 1-2 sentences at a time.
Listen to what the agent says and respond appropriately.
If they ask for verification, provide it (last 4 of card: 4532, birthday: March 15)."""
        )
        
        # Agent helping the customer - male voice
        self.agent = NovaSonicParticipant(
            name="AGENT",
            voice_id="matthew",  # Male voice
            system_prompt="""You are Alex, a friendly and helpful bank customer service representative.
A customer is calling about their account.

Start by greeting them professionally: "Thank you for calling First National Bank. My name is Alex, how can I help you today?"

Listen to their concern carefully. If they mention a suspicious charge:
1. Express understanding and empathy
2. Ask them to verify their identity (last 4 digits of card and birthday)
3. Once verified, look up the charge and explain it (it's likely an Amazon Prime subscription)
4. Offer to help cancel or dispute if they want

Keep responses friendly, professional, and concise - 1-2 sentences at a time.
Always make the customer feel heard and helped."""
        )
        
    async def run(self, max_turns=10, turn_duration=8):
        """Run the conversation."""
        print("=" * 60)
        print("🎭 AI-to-AI CONVERSATION")
        print("=" * 60)
        print("Customer (Ruth voice) <---> Agent (Matthew voice)")
        print("-" * 60)
        
        # Connect both participants
        await self.customer.connect()
        await self.agent.connect()
        
        # Setup sessions
        await self.customer.setup_session()
        await self.agent.setup_session()
        
        # Start receiver tasks
        customer_rx = asyncio.create_task(self.customer.receive_responses())
        agent_rx = asyncio.create_task(self.agent.receive_responses())
        
        # Start audio routing tasks
        customer_tx = asyncio.create_task(self.customer.send_audio_from_queue())
        agent_tx = asyncio.create_task(self.agent.send_audio_from_queue())
        
        print("\n" + "=" * 60)
        print("CONVERSATION START")
        print("=" * 60 + "\n")
        
        # Let the agent start first (they typically greet)
        # Send initial silence to agent to trigger their greeting
        initial_silence = b'\x00' * 640 * 50  # 1 second of silence
        for i in range(0, len(initial_silence), 640):
            await self.agent.audio_in_queue.put(initial_silence[i:i+640])
        
        # Route audio between them for the conversation
        turn = 0
        while turn < max_turns:
            turn += 1
            print(f"\n--- Turn {turn} ---")
            
            # Let them exchange audio for a few seconds
            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < turn_duration:
                # Route agent's audio output to customer's input
                try:
                    agent_audio = await asyncio.wait_for(self.agent.audio_out_queue.get(), timeout=0.05)
                    await self.customer.audio_in_queue.put(agent_audio)
                except asyncio.TimeoutError:
                    pass
                
                # Route customer's audio output to agent's input
                try:
                    customer_audio = await asyncio.wait_for(self.customer.audio_out_queue.get(), timeout=0.05)
                    await self.agent.audio_in_queue.put(customer_audio)
                except asyncio.TimeoutError:
                    pass
                    
            # Check if conversation seems stalled
            if not self.customer.texts and not self.agent.texts:
                print("[!] No responses yet, sending more silence to agent...")
                for _ in range(50):
                    await self.agent.audio_in_queue.put(b'\x00' * 640)
        
        print("\n" + "=" * 60)
        print("CONVERSATION END")
        print("=" * 60)
        
        # Stop everything
        self.customer.done = True
        self.agent.done = True
        
        for task in [customer_rx, agent_rx, customer_tx, agent_tx]:
            task.cancel()
            
        await self.customer.cleanup()
        await self.agent.cleanup()
        
        # Save audio files
        os.makedirs("voice_output", exist_ok=True)
        
        if self.customer.all_audio:
            self.save_audio("voice_output/customer_sarah.wav", self.customer.all_audio)
            
        if self.agent.all_audio:
            self.save_audio("voice_output/agent_alex.wav", self.agent.all_audio)
            
        # Print transcript
        print("\n" + "=" * 60)
        print("TRANSCRIPT")
        print("=" * 60)
        print(f"Customer responses: {len(self.customer.texts)}")
        print(f"Agent responses: {len(self.agent.texts)}")
        
    def save_audio(self, filename: str, audio_chunks: list):
        """Save audio chunks to WAV file."""
        audio_data = b''.join(audio_chunks)
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(OUTPUT_RATE)
            wf.writeframes(audio_data)
        print(f"Saved: {filename} ({len(audio_data)} bytes)")


async def main():
    conv = AItoAIConversation()
    await conv.run(max_turns=8, turn_duration=10)

if __name__ == "__main__":
    asyncio.run(main())
