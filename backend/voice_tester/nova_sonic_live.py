#!/usr/bin/env python3
"""Nova Sonic Live - Based on working concurrent test pattern."""

import asyncio
import base64
import json
import os
import queue
import numpy as np
import sounddevice as sd
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

INPUT_RATE = 16000
OUTPUT_RATE = 24000

class NovaSonicLive:
    def __init__(self):
        self.stream = None
        self.done = False
        self.prompt = "p1"
        self.mic_queue = queue.Queue()
        self.speaker_queue = queue.Queue()
        self.audio_chunks = []
        self.texts = []
        
    async def send(self, data):
        await self.stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps(data).encode())
            )
        )
        
    def mic_callback(self, indata, frames, time, status):
        audio = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        self.mic_queue.put(audio)
        
    def speaker_callback(self, outdata, frames, time, status):
        data = b''
        needed = frames * 2
        while len(data) < needed:
            try:
                data += self.speaker_queue.get_nowait()
            except queue.Empty:
                break
        if data:
            audio = np.frombuffer(data[:needed], dtype=np.int16).astype(np.float32) / 32767
            if len(audio) < frames:
                audio = np.pad(audio, (0, frames - len(audio)))
            outdata[:, 0] = audio[:frames]
        else:
            outdata.fill(0)
            
    async def receive_responses(self):
        print("[RX] Started")
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
                                self.texts.append(text)
                                if role == 'USER':
                                    print(f"\n🎤 You: {text}")
                                elif 'interrupted' not in text:
                                    print(f"\n🤖 Nova: {text}")
                            elif 'audioOutput' in evt:
                                audio = base64.b64decode(evt['audioOutput']['content'])
                                self.audio_chunks.append(audio)
                                self.speaker_queue.put(audio)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if "closed" not in str(e).lower():
                        print(f"[RX] Error: {e}")
                    break
        except asyncio.CancelledError:
            pass
        print(f"[RX] Stopped (got {len(self.audio_chunks)} audio chunks)")

    async def run(self, duration=30):
        print("=" * 50)
        print("NOVA SONIC LIVE CONVERSATION")
        print("=" * 50)
        
        # Connect
        config = Config(
            endpoint_uri="https://bedrock-runtime.us-east-1.amazonaws.com",
            region="us-east-1",
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        client = BedrockRuntimeClient(config=config)
        self.stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id='amazon.nova-sonic-v1:0')
        )
        print("Connected to Nova Sonic")
        
        # Start audio FIRST
        mic = sd.InputStream(samplerate=INPUT_RATE, channels=1, callback=self.mic_callback, 
                            blocksize=640, dtype=np.float32)
        spk = sd.OutputStream(samplerate=OUTPUT_RATE, channels=1, callback=self.speaker_callback,
                             blocksize=1920, dtype=np.float32)
        mic.start()
        spk.start()
        print("Audio streams started")
        
        # Give mic time to start
        await asyncio.sleep(0.2)
        
        # Start receiver
        rx_task = asyncio.create_task(self.receive_responses())
        
        # Session setup
        await self.send({"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024}}}})
        await self.send({"event": {"promptStart": {
            "promptName": self.prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm", "sampleRateHertz": OUTPUT_RATE,
                "sampleSizeBits": 16, "channelCount": 1, "voiceId": "matthew",
                "encoding": "base64", "audioType": "SPEECH"
            }
        }}})
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt, "contentName": "sys", "type": "TEXT",
            "interactive": False, "role": "SYSTEM",
            "textInputConfiguration": {"mediaType": "text/plain"}
        }}})
        await self.send({"event": {"textInput": {
            "promptName": self.prompt, "contentName": "sys",
            "content": "You are a friendly voice assistant. Keep responses to 1-2 sentences."
        }}})
        await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": "sys"}}})
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt, "contentName": "audio1", "type": "AUDIO",
            "interactive": True, "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm", "sampleRateHertz": INPUT_RATE,
                "sampleSizeBits": 16, "channelCount": 1, "audioType": "SPEECH", "encoding": "base64"
            }
        }}})
        print("Speak now! (VAD will detect when you stop)")
        print("-" * 50)
        
        # Stream mic audio
        chunks_sent = 0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < duration:
            try:
                audio = self.mic_queue.get(timeout=0.02)
                await self.send({"event": {"audioInput": {
                    "promptName": self.prompt, "contentName": "audio1",
                    "content": base64.b64encode(audio).decode()
                }}})
                chunks_sent += 1
                if chunks_sent % 100 == 0:
                    print(f"[TX] {chunks_sent} chunks sent")
            except queue.Empty:
                await asyncio.sleep(0.01)
        
        print(f"\nTime up! Sent {chunks_sent} chunks")
        self.done = True
        
        mic.stop(); spk.stop()
        mic.close(); spk.close()
        rx_task.cancel()
        
        try:
            await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": "audio1"}}})
            await self.send({"event": {"promptEnd": {"promptName": self.prompt}}})
            await self.send({"event": {"sessionEnd": {}}})
        except:
            pass
        
        print(f"Done (received {len(self.audio_chunks)} audio chunks)")

if __name__ == "__main__":
    asyncio.run(NovaSonicLive().run(30))
