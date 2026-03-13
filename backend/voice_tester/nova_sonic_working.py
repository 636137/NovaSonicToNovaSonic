#!/usr/bin/env python3
"""Nova Sonic working test"""
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


async def main():
    print("=== NOVA SONIC TEST ===")
    
    # Generate test audio with Polly
    polly = boto3.client('polly', region_name='us-east-1')
    audio = polly.synthesize_speech(
        Text="Hello, how are you today?",
        OutputFormat='pcm',
        SampleRate='16000',
        VoiceId='Matthew',
        Engine='neural'
    )['AudioStream'].read()
    print(f"Input audio: {len(audio)} bytes")
    
    # Create Bedrock client
    config = Config(
        endpoint_uri="https://bedrock-runtime.us-east-1.amazonaws.com",
        region="us-east-1",
        aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)
    
    print("Starting Nova Sonic stream...")
    stream = await client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id="amazon.nova-sonic-v1:0")
    )
    
    async def send(data):
        await stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps(data).encode())
            )
        )
    
    prompt = "p1"
    
    # 1. Session start
    print("1. Session start")
    await send({"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024}}}})
    
    # 2. Prompt start with audio output config
    print("2. Prompt start")
    await send({"event": {"promptStart": {
        "promptName": prompt,
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
    
    # 3. System prompt (REQUIRED first)
    print("3. System content")
    await send({"event": {"contentStart": {
        "promptName": prompt,
        "contentName": "sys",
        "type": "TEXT",
        "interactive": False,
        "role": "SYSTEM",
        "textInputConfiguration": {"mediaType": "text/plain"}
    }}})
    await send({"event": {"textInput": {
        "promptName": prompt,
        "contentName": "sys",
        "content": "You are a helpful assistant. Listen to the audio and respond briefly and naturally."
    }}})
    await send({"event": {"contentEnd": {"promptName": prompt, "contentName": "sys"}}})
    
    # 4. Audio input content
    print("4. Audio input start")
    await send({"event": {"contentStart": {
        "promptName": prompt,
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
    
    # 5. Stream audio chunks - need to simulate real-time streaming
    print("5. Streaming audio...")
    chunk_size = 320  # 20ms of audio at 16kHz
    chunks_sent = 0
    for i in range(0, len(audio), chunk_size):
        chunk = audio[i:i+chunk_size]
        await send({"event": {"audioInput": {
            "promptName": prompt,
            "contentName": "audio1",
            "content": base64.b64encode(chunk).decode()
        }}})
        chunks_sent += 1
        # Simulate real-time: 20ms of audio takes 20ms to speak
        await asyncio.sleep(0.02)
    print(f"   Sent {chunks_sent} chunks")
    
    # 6. End audio content
    print("6. End audio content")
    await send({"event": {"contentEnd": {"promptName": prompt, "contentName": "audio1"}}})
    
    # Small delay to let server process
    await asyncio.sleep(0.5)
    
    # 7. Collect responses - need longer timeout for processing
    print("7. Waiting for response...")
    audio_chunks = []
    texts = []
    timeout_count = 0
    max_timeouts = 15  # Allow more timeouts (30 seconds total)
    
    for _ in range(200):
        try:
            output = await asyncio.wait_for(stream.await_output(), timeout=2.0)
            result = await output[1].receive()
            timeout_count = 0  # Reset on success
            if result.value and result.value.bytes_:
                data = json.loads(result.value.bytes_.decode())
                if 'event' in data:
                    evt = data['event']
                    if 'textOutput' in evt:
                        texts.append(evt['textOutput']['content'])
                        print(f"   TEXT: {evt['textOutput']['content'][:80]}")
                    elif 'audioOutput' in evt:
                        audio_chunks.append(base64.b64decode(evt['audioOutput']['content']))
                        print(f"   AUDIO chunk: {len(audio_chunks[-1])} bytes")
                    elif 'contentEnd' in evt:
                        print("   Content ended")
                        if audio_chunks:
                            break
                    elif 'error' in evt or 'modelStreamError' in evt:
                        print(f"   ERROR: {evt}")
                        break
        except asyncio.TimeoutError:
            timeout_count += 1
            if timeout_count >= max_timeouts:
                print(f"   Max timeouts reached ({max_timeouts})")
                break
            if audio_chunks:
                print(f"   Got audio, stopping")
                break
            print(f"   (waiting... {timeout_count})")
    
    # 8. Clean up
    print("8. Closing stream...")
    try:
        await send({"event": {"promptEnd": {"promptName": prompt}}})
        await send({"event": {"sessionEnd": {}}})
        await stream.input_stream.close()
    except:
        pass
    
    # Results
    print("\n=== RESULTS ===")
    print(f"Text outputs: {len(texts)}")
    print(f"Audio chunks: {len(audio_chunks)}")
    
    if texts:
        print("\nTranscript/Response:")
        for t in texts:
            print(f"  {t}")
    
    if audio_chunks:
        total_audio = b''.join(audio_chunks)
        output_path = '/Users/ChadDHendren/AmazonConnect1/voice_output/nova_sonic_output.wav'
        with wave.open(output_path, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(total_audio)
        print(f"\nSaved: {output_path} ({len(total_audio)} bytes)")
        print(f"Play with: afplay {output_path}")
        return True
    
    print("\nNo audio output received from Nova Sonic")
    return False


if __name__ == "__main__":
    import sys
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
