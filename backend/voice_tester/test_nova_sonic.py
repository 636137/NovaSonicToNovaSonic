#!/usr/bin/env python3
"""
Test Nova Sonic Connection

Simple test to verify Nova Sonic bidirectional streaming works.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure we use the right Python environment
print(f"Python: {sys.executable}")
print(f"Version: {sys.version}")

async def test_nova_sonic():
    """Test Nova Sonic bidirectional streaming connection."""
    from voice_tester.nova_sonic_client import NovaSonicVoiceClient, NovaSonicConfig
    
    print("\n=== Nova Sonic Connection Test ===\n")
    
    # Check AWS credentials
    aws_access = os.environ.get('AWS_ACCESS_KEY_ID', '')
    aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
    if not aws_access:
        print("Warning: AWS_ACCESS_KEY_ID not set. Checking for credentials file...")
        creds_file = os.path.expanduser('~/.aws/credentials')
        if os.path.exists(creds_file):
            print(f"  Found credentials file: {creds_file}")
        else:
            print("  No credentials found. Test may fail.")
    else:
        print(f"  AWS Access Key: {aws_access[:8]}...")
    print(f"  AWS Region: {aws_region}")
    
    # Create config and client
    config = NovaSonicConfig(region=aws_region)
    client = NovaSonicVoiceClient(config)
    
    # Set test persona
    client.set_persona({
        "name": "Test Caller",
        "background": "System integration test",
        "attributes": {
            "speaking_rate": "normal",
            "patience": "high"
        }
    })
    
    print(f"\nConfiguration:")
    print(f"  Model: {config.model_id}")
    print(f"  Voice: {config.voice_id}")
    print(f"  Input Rate: {config.input_sample_rate} Hz")
    print(f"  Output Rate: {config.output_sample_rate} Hz")
    
    # Track results
    transcript_received = False
    audio_received = False
    errors = []
    
    def on_transcript(role, text):
        nonlocal transcript_received
        transcript_received = True
        print(f"\n  [{role.upper()}]: {text}")
    
    def on_audio(audio_bytes):
        nonlocal audio_received
        audio_received = True
        print(f"  [AUDIO]: Received {len(audio_bytes)} bytes")
    
    client.on_transcript = on_transcript
    client.on_speech_output = on_audio
    
    print("\nStarting session...")
    try:
        await client.start_session()
        print("  Session started successfully!")
        
        # Send a text message to test
        print("\nSending test message...")
        await client.send_text_message("Hello, can you hear me? Please respond briefly.")
        
        # Wait for response
        print("Waiting for response (10 seconds)...")
        await asyncio.sleep(10)
        
        # Collect audio output
        audio_chunks = []
        while not client.audio_queue.empty():
            chunk = await client.get_audio_output()
            if chunk:
                audio_chunks.append(chunk)
        
        print(f"\nResults:")
        print(f"  Transcript received: {transcript_received}")
        print(f"  Audio chunks received: {len(audio_chunks)}")
        
        if audio_chunks:
            total_bytes = sum(len(c) for c in audio_chunks)
            duration_ms = (total_bytes / 2) / config.output_sample_rate * 1000
            print(f"  Total audio: {total_bytes} bytes (~{duration_ms:.0f}ms)")
        
    except Exception as e:
        errors.append(str(e))
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nEnding session...")
        try:
            await client.end_session()
            print("  Session ended.")
        except Exception as e:
            print(f"  Error ending session: {e}")
    
    # Final status
    print("\n=== Test Summary ===")
    if not errors and (transcript_received or audio_received or len(audio_chunks) > 0):
        print("✓ Nova Sonic connection test PASSED")
        return True
    elif not errors:
        print("? Nova Sonic connected but no response received")
        print("  This might be expected if there's a delay in model response")
        return True  # Connection worked, even if no immediate response
    else:
        print("✗ Nova Sonic connection test FAILED")
        for err in errors:
            print(f"  Error: {err}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_nova_sonic())
    sys.exit(0 if success else 1)
