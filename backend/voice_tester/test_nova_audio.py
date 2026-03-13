#!/usr/bin/env python3
"""
Test Nova Sonic with actual audio input.

Nova Sonic is speech-to-speech - it REQUIRES audio input.
"""
import asyncio
import base64
import json
import os
import sys
import wave
import struct
from pathlib import Path

import boto3

# Set up credentials
session = boto3.Session()
credentials = session.get_credentials()
if credentials:
    frozen = credentials.get_frozen_credentials()
    os.environ['AWS_ACCESS_KEY_ID'] = frozen.access_key
    os.environ['AWS_SECRET_ACCESS_KEY'] = frozen.secret_key
    if frozen.token:
        os.environ['AWS_SESSION_TOKEN'] = frozen.token

from aws_sdk_bedrock_runtime.client import (
    BedrockRuntimeClient,
    InvokeModelWithBidirectionalStreamOperationInput
)
from aws_sdk_bedrock_runtime.models import (
    InvokeModelWithBidirectionalStreamInputChunk,
    BidirectionalInputPayloadPart
)
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver


def generate_test_audio_speech():
    """Generate test audio using Polly."""
    polly = boto3.client('polly', region_name='us-east-1')
    response = polly.synthesize_speech(
        Text="Hello, I am calling to test the system. Can you hear me?",
        OutputFormat='pcm',
        SampleRate='16000',
        VoiceId='Matthew',
        Engine='neural'
    )
    return response['AudioStream'].read()


async def test_nova_sonic_with_audio():
    """Test Nova Sonic with real audio input."""
    
    print("="*60)
    print("NOVA SONIC WITH AUDIO INPUT")
    print("="*60)
    
    # Generate test audio
    print("Generating test audio with Polly...")
    audio_data = generate_test_audio_speech()
    print(f"Generated {len(audio_data)} bytes of audio")
    
    # Create client
    config = Config(
        endpoint_uri="https://bedrock-runtime.us-east-1.amazonaws.com",
        region="us-east-1",
        aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)
    
    print("\nStarting Nova Sonic stream...")
    stream = await client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id="amazon.nova-2-sonic-v1:0")
    )
    
    async def send_event(event_json: str):
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        await stream.input_stream.send(event)
    
    prompt_name = "test-prompt"
    
    # Session start
    print("Sending session start...")
    await send_event(json.dumps({
        "event": {
            "sessionStart": {
                "inferenceConfiguration": {
                    "maxTokens": 1024,
                    "topP": 0.9,
                    "temperature": 0.7
                }
            }
        }
    }))
    
    # Prompt start with audio output
    print("Sending prompt start...")
    await send_event(json.dumps({
        "event": {
            "promptStart": {
                "promptName": prompt_name,
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
            }
        }
    }))
    
    # System prompt (required first)
    sys_content = "system-1"
    print("Sending SYSTEM prompt...")
    await send_event(json.dumps({
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": sys_content,
                "type": "TEXT",
                "interactive": False,
                "role": "SYSTEM",
                "textInputConfiguration": {"mediaType": "text/plain"}
            }
        }
    }))
    await send_event(json.dumps({
        "event": {
            "textInput": {
                "promptName": prompt_name,
                "contentName": sys_content,
                "content": "You are a friendly voice assistant. Listen to the user and respond helpfully. Keep responses brief and natural."
            }
        }
    }))
    await send_event(json.dumps({
        "event": {
            "contentEnd": {
                "promptName": prompt_name,
                "contentName": sys_content
            }
        }
    }))
    
    # Audio input
    audio_content = "audio-1"
    print("Sending AUDIO content start...")
    await send_event(json.dumps({
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": audio_content,
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
            }
        }
    }))
    
    # Send audio in chunks
    chunk_size = 4096
    print(f"Streaming {len(audio_data)} bytes of audio in {len(audio_data)//chunk_size} chunks...")
    
    for i in range(0, len(audio_data), chunk_size):
        chunk = audio_data[i:i+chunk_size]
        chunk_b64 = base64.b64encode(chunk).decode('utf-8')
        await send_event(json.dumps({
            "event": {
                "audioInput": {
                    "promptName": prompt_name,
                    "contentName": audio_content,
                    "content": chunk_b64
                }
            }
        }))
        await asyncio.sleep(0.01)
    
    # End audio content
    print("Ending audio content...")
    await send_event(json.dumps({
        "event": {
            "contentEnd": {
                "promptName": prompt_name,
                "contentName": audio_content
            }
        }
    }))
    
    # Collect responses
    print("\nWaiting for Nova Sonic response...")
    audio_chunks = []
    text_outputs = []
    
    try:
        for _ in range(100):
            try:
                output = await asyncio.wait_for(stream.await_output(), timeout=1.0)
                result = await output[1].receive()
                
                if result.value and result.value.bytes_:
                    data = json.loads(result.value.bytes_.decode('utf-8'))
                    
                    if 'event' in data:
                        event = data['event']
                        
                        if 'textOutput' in event:
                            text = event['textOutput']['content']
                            text_outputs.append(text)
                            print(f"  Text: {text}")
                            
                        elif 'audioOutput' in event:
                            audio = base64.b64decode(event['audioOutput']['content'])
                            audio_chunks.append(audio)
                            print(f"  Audio chunk: {len(audio)} bytes")
                            
                        elif 'contentEnd' in event:
                            print("  Content ended")
                            if audio_chunks:
                                break
                            
            except asyncio.TimeoutError:
                if audio_chunks:
                    break
                    
    except Exception as e:
        print(f"Error: {e}")
    
    # Clean up
    print("\nClosing stream...")
    try:
        await send_event(json.dumps({"event": {"promptEnd": {"promptName": prompt_name}}}))
        await send_event(json.dumps({"event": {"sessionEnd": {}}}))
        await stream.input_stream.close()
    except:
        pass
    
    # Results
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Text outputs: {len(text_outputs)}")
    print(f"Audio chunks: {len(audio_chunks)}")
    
    if text_outputs:
        print("\nTranscript/Response:")
        for t in text_outputs:
            print(f"  {t}")
    
    if audio_chunks:
        total_audio = b''.join(audio_chunks)
        print(f"\nTotal audio: {len(total_audio)} bytes")
        
        output_path = '/Users/ChadDHendren/AmazonConnect1/voice_output/nova_audio_response.wav'
        with wave.open(output_path, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(total_audio)
        print(f"Saved to: {output_path}")
        print(f"Play with: afplay {output_path}")
    else:
        print("\nNo audio generated.")
    
    return len(audio_chunks) > 0


if __name__ == "__main__":
    success = asyncio.run(test_nova_sonic_with_audio())
    sys.exit(0 if success else 1)
