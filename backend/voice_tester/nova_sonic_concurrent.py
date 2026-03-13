#!/usr/bin/env python3
"""
Nova Sonic Working Implementation

Key insight: Nova Sonic bidirectional streaming requires CONCURRENT 
handling of input and output streams. We can't just send all input 
then wait for output - they must run in parallel.
"""
import asyncio
import base64
import json
import os
import wave
import boto3

# Set credentials from boto3 session
session = boto3.Session()
creds = session.get_credentials().get_frozen_credentials()
os.environ['AWS_ACCESS_KEY_ID'] = creds.access_key
os.environ['AWS_SECRET_ACCESS_KEY'] = creds.secret_key
if creds.token:
    os.environ['AWS_SESSION_TOKEN'] = creds.token

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver


class NovaSonicTest:
    def __init__(self):
        self.stream = None
        self.audio_chunks = []
        self.texts = []
        self.done = False
        self.prompt = "p1"
        
    async def send(self, data):
        """Send an event to Nova Sonic."""
        await self.stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps(data).encode())
            )
        )
        
    async def receive_responses(self):
        """Receive responses from Nova Sonic in background."""
        print("[RX] Starting response receiver...")
        content_ended_count = 0
        try:
            while not self.done:
                try:
                    output = await asyncio.wait_for(self.stream.await_output(), timeout=1.0)
                    result = await output[1].receive()
                    
                    if result.value and result.value.bytes_:
                        data = json.loads(result.value.bytes_.decode())
                        if 'event' in data:
                            evt = data['event']
                            
                            if 'contentStart' in evt:
                                role = evt['contentStart'].get('role', '')
                                ctype = evt['contentStart'].get('type', '')
                                print(f"[RX] Content start: role={role} type={ctype}")
                            
                            elif 'textOutput' in evt:
                                text = evt['textOutput']['content']
                                self.texts.append(text)
                                print(f"[RX] TEXT: {text}")
                                
                            elif 'audioOutput' in evt:
                                audio = base64.b64decode(evt['audioOutput']['content'])
                                self.audio_chunks.append(audio)
                                print(f"[RX] AUDIO: {len(audio)} bytes (total chunks: {len(self.audio_chunks)})")
                                
                            elif 'contentEnd' in evt:
                                content_ended_count += 1
                                print(f"[RX] Content ended (#{content_ended_count})")
                                # Wait for potentially more content
                                
                            elif 'error' in evt:
                                print(f"[RX] ERROR: {evt['error']}")
                                
                            else:
                                # Print full event for debugging
                                print(f"[RX] Other event: {json.dumps(evt, default=str)[:200]}")
                                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if "closed" not in str(e).lower():
                        print(f"[RX] Error: {e}")
                    break
        except asyncio.CancelledError:
            print("[RX] Receiver cancelled")
        print(f"[RX] Receiver stopped (got {content_ended_count} content ends)")
        
    async def send_audio_input(self, audio_data: bytes):
        """Send audio data to Nova Sonic."""
        print(f"[TX] Starting to send {len(audio_data)} bytes of audio...")
        
        # 1. Session start
        await self.send({"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024}}}})
        print("[TX] Session started")
        
        # 2. Prompt start with audio output config
        await self.send({"event": {"promptStart": {
            "promptName": self.prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 24000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": "matthew",
                "encoding": "base64",
                "audioType": "SPEECH"
            }
        }}})
        print("[TX] Prompt configured")
        
        # 3. System prompt (REQUIRED first)
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
            "content": "You are a conversational voice assistant. When the user speaks to you, you MUST respond with speech. Always give a verbal response. Be friendly and helpful. Say something back to the user."
        }}})
        await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": "sys"}}})
        print("[TX] System prompt sent")
        
        # 4. Audio input content start
        await self.send({"event": {"contentStart": {
            "promptName": self.prompt,
            "contentName": "audio1",
            "type": "AUDIO",
            "interactive": True,
            "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 16000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64"
            }
        }}})
        print("[TX] Audio content started")
        
        # 5. Stream audio in small real-time chunks (20ms each)
        chunk_size = 640  # 20ms at 16kHz, 16-bit mono
        total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i+chunk_size]
            await self.send({"event": {"audioInput": {
                "promptName": self.prompt,
                "contentName": "audio1",
                "content": base64.b64encode(chunk).decode()
            }}})
            # Send at real-time pace for VAD to work properly
            await asyncio.sleep(0.02)
            
        print(f"[TX] Sent {total_chunks} audio chunks")
        
        # 6. Send 2 seconds of silence so VAD detects end of speech
        # Nova Sonic uses VAD - it needs silence to know user stopped talking
        silence = b'\x00' * 640  # 20ms of silence
        for _ in range(100):  # 2 seconds of silence (100 x 20ms)
            await self.send({"event": {"audioInput": {
                "promptName": self.prompt,
                "contentName": "audio1",
                "content": base64.b64encode(silence).decode()
            }}})
            await asyncio.sleep(0.02)
        print("[TX] Sent 2s of silence for VAD")
        
        # 7. Wait for model response - DO NOT send contentEnd yet!
        # Keep audio stream "open" like a real microphone would be
        got_audio = False
        last_audio_time = 0
        
        for i in range(60):  # Wait up to 60 seconds
            await asyncio.sleep(1)
            
            if self.audio_chunks:
                if len(self.audio_chunks) > last_audio_time:
                    last_audio_time = len(self.audio_chunks)
                    print(f"[TX] Receiving audio... {len(self.audio_chunks)} chunks")
                    continue
                else:
                    # No new audio for 1 second after receiving some
                    print(f"[TX] Audio complete: {len(self.audio_chunks)} chunks")
                    got_audio = True
                    await asyncio.sleep(2)
                    break
            
            # Check for response text
            has_assistant = any("Hi" in t or "assist" in t.lower() or "help" in t.lower() for t in self.texts if "hello" not in t.lower())
            if has_assistant and i > 3:
                # Got text response, wait a bit more for audio
                print(f"[TX] Got assistant text, waiting for audio... ({i+1}s)")
                    
            if i % 10 == 9:
                print(f"[TX] Waiting... texts={len(self.texts)} audio={len(self.audio_chunks)} ({i+1}s)")
        
        # 8. NOW end the audio content after receiving response
        self.done = True
        await asyncio.sleep(1)
        try:
            await self.send({"event": {"contentEnd": {"promptName": self.prompt, "contentName": "audio1"}}})
            await self.send({"event": {"promptEnd": {"promptName": self.prompt}}})
            await self.send({"event": {"sessionEnd": {}}})
        except:
            pass
        print(f"[TX] Session ended (got_audio={got_audio})")
        
    async def run(self):
        """Run the Nova Sonic test."""
        print("=== NOVA SONIC CONCURRENT TEST ===")
        
        # Generate test audio with Polly
        polly = boto3.client('polly', region_name='us-east-1')
        audio = polly.synthesize_speech(
            Text="Hello, can you hear me? I want to test this voice system.",
            OutputFormat='pcm',
            SampleRate='16000',
            VoiceId='Matthew',
            Engine='neural'
        )['AudioStream'].read()
        print(f"Generated {len(audio)} bytes of input audio")
        
        # Create Bedrock client
        config = Config(
            endpoint_uri="https://bedrock-runtime.us-east-1.amazonaws.com",
            region="us-east-1",
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        client = BedrockRuntimeClient(config=config)
        
        print("Starting Nova Sonic stream...")
        self.stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id="amazon.nova-sonic-v1:0")
        )
        print("Stream connected")
        
        # Start receiver in background
        receiver = asyncio.create_task(self.receive_responses())
        
        # Send input (this also waits for response)
        await self.send_audio_input(audio)
        
        # Give receiver time to finish
        await asyncio.sleep(2)
        receiver.cancel()
        
        try:
            await receiver
        except asyncio.CancelledError:
            pass
            
        # Close stream
        try:
            await self.stream.input_stream.close()
        except:
            pass
        
        # Report results
        print("\n=== RESULTS ===")
        print(f"Text responses: {len(self.texts)}")
        print(f"Audio chunks: {len(self.audio_chunks)}")
        
        if self.texts:
            print("\nTranscripts:")
            for t in self.texts:
                print(f"  {t}")
                
        if self.audio_chunks:
            total = b''.join(self.audio_chunks)
            output_path = '/Users/ChadDHendren/AmazonConnect1/voice_output/nova_sonic_output.wav'
            with wave.open(output_path, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(total)
            print(f"\nAudio saved: {output_path} ({len(total)} bytes)")
            print(f"Play: afplay {output_path}")
            return True
            
        print("\nNo audio output :(")
        return False


async def main():
    test = NovaSonicTest()
    return await test.run()


if __name__ == "__main__":
    import sys
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
