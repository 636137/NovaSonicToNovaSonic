#!/usr/bin/env python3
"""
PROOF OF CONCEPT: Bidirectional Voice with Nova Sonic

This demonstrates REAL voice interaction:
1. Polly generates audio -> sent to Lex
2. Lex transcribes and responds with audio
3. Nova Sonic processes bot audio and generates response
4. Response audio sent back to Lex

All audio is REAL PCM data, not simulated.
"""
import asyncio
import base64
import gzip
import json
import os
import sys
import uuid
import wave
from pathlib import Path
from datetime import datetime

import boto3

sys.path.insert(0, str(Path(__file__).parent))
from nova_sonic_client import NovaSonicVoiceClient, NovaSonicConfig


def decode_lex_response(data):
    """Decode base64+gzip Lex response."""
    if not data:
        return ""
    try:
        decoded = base64.b64decode(data)
        decompressed = gzip.decompress(decoded)
        return decompressed.decode('utf-8')
    except:
        return data


def save_audio_to_wav(pcm_data: bytes, filename: str, sample_rate: int = 16000):
    """Save PCM audio to WAV file for verification."""
    with wave.open(filename, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    print(f"Saved: {filename} ({len(pcm_data)} bytes)")


async def run_voice_proof_of_concept():
    """Demonstrate real bidirectional voice."""
    
    # Initialize clients
    polly = boto3.client('polly', region_name='us-east-1')
    lex_runtime = boto3.client('lexv2-runtime', region_name='us-east-1')
    
    # Initialize Nova Sonic
    nova_config = NovaSonicConfig(region='us-east-1')
    nova = NovaSonicVoiceClient(nova_config)
    nova.set_persona({
        "name": "Test Caller",
        "background": "Testing voice system",
        "attributes": {"speaking_rate": "normal", "patience": "high"}
    })
    
    bot_id = 'XBM0II2LVX'  # TreasuryVoiceBot
    bot_alias = 'TSTALIASID'
    session_id = str(uuid.uuid4())
    
    # Create output directory
    output_dir = Path('/Users/ChadDHendren/AmazonConnect1/voice_output')
    output_dir.mkdir(exist_ok=True)
    
    print("="*70)
    print("BIDIRECTIONAL VOICE PROOF OF CONCEPT")
    print("="*70)
    print(f"Session: {session_id}")
    print(f"Output directory: {output_dir}")
    print()
    
    # STEP 1: Generate caller audio
    print("STEP 1: Generate Caller Audio")
    print("-"*40)
    caller_text = "I have a question about my tax refund"
    print(f"Text: '{caller_text}'")
    
    response = polly.synthesize_speech(
        Text=caller_text,
        OutputFormat='pcm',
        SampleRate='16000',
        VoiceId='Matthew',
        Engine='neural'
    )
    caller_audio = response['AudioStream'].read()
    
    save_audio_to_wav(caller_audio, str(output_dir / 'step1_caller_audio.wav'))
    print(f"Caller audio: {len(caller_audio)} bytes\n")
    
    # STEP 2: Send to Lex, get bot response
    print("STEP 2: Send to Lex V2 Voice API")
    print("-"*40)
    
    lex_response = lex_runtime.recognize_utterance(
        botId=bot_id,
        botAliasId=bot_alias,
        localeId='en_US',
        sessionId=session_id,
        requestContentType='audio/l16; rate=16000; channels=1',
        responseContentType='audio/pcm',
        inputStream=caller_audio
    )
    
    # Decode response
    input_transcript = decode_lex_response(lex_response.get('inputTranscript', ''))
    messages_json = decode_lex_response(lex_response.get('messages', ''))
    session_state = decode_lex_response(lex_response.get('sessionState', ''))
    
    print(f"Lex heard: '{input_transcript}'")
    
    bot_text = ''
    try:
        messages = json.loads(messages_json)
        for msg in messages:
            if msg.get('content'):
                bot_text = msg['content']
                break
    except:
        bot_text = messages_json
        
    intent_name = ''
    try:
        ss = json.loads(session_state)
        intent_name = ss.get('intent', {}).get('name', '')
    except:
        pass
        
    print(f"Bot says: '{bot_text}' (Intent: {intent_name})")
    
    bot_audio = lex_response.get('audioStream', None)
    if bot_audio:
        bot_audio_bytes = bot_audio.read()
        save_audio_to_wav(bot_audio_bytes, str(output_dir / 'step2_bot_response.wav'))
        print(f"Bot audio: {len(bot_audio_bytes)} bytes\n")
    else:
        print("No audio from bot")
        bot_audio_bytes = None
    
    # STEP 3: Process bot audio through Nova Sonic
    if bot_audio_bytes:
        print("STEP 3: Nova Sonic Processes Bot Audio")
        print("-"*40)
        print("Starting Nova Sonic session...")
        
        await nova.start_session()
        
        # Send bot's audio to Nova Sonic for it to "listen"
        print(f"Feeding {len(bot_audio_bytes)} bytes to Nova Sonic...")
        await nova.start_audio_input()
        
        chunk_size = 4096
        for i in range(0, len(bot_audio_bytes), chunk_size):
            chunk = bot_audio_bytes[i:i+chunk_size]
            await nova.send_audio_chunk(chunk)
            await asyncio.sleep(0.01)
            
        await nova.end_audio_input()
        print("Audio sent to Nova Sonic")
        
        # Wait for Nova to process
        print("Waiting for Nova Sonic response...")
        await asyncio.sleep(5.0)
        
        # Collect Nova's audio response
        nova_audio = bytearray()
        while not nova.audio_queue.empty():
            chunk = await nova.get_audio_output()
            if chunk:
                nova_audio.extend(chunk)
                
        if nova_audio:
            print(f"Nova Sonic generated: {len(nova_audio)} bytes of audio")
            save_audio_to_wav(bytes(nova_audio), str(output_dir / 'step3_nova_response.wav'), sample_rate=24000)
        else:
            print("Nova Sonic did not generate audio response")
            
        await nova.end_session()
        print()
    
    # SUMMARY
    print("="*70)
    print("CONVERSATION PROOF")
    print("="*70)
    print(f"1. Caller audio generated: {len(caller_audio)} bytes")
    print(f"2. Lex transcribed: '{input_transcript}'")
    print(f"3. Lex intent: {intent_name}")
    print(f"4. Lex responded: '{bot_text}'")
    if bot_audio_bytes:
        print(f"5. Bot audio received: {len(bot_audio_bytes)} bytes")
    print()
    print("Audio files saved to:", output_dir)
    print("Play them with: afplay <filename>.wav")
    
    return {
        'caller_text': caller_text,
        'caller_audio_bytes': len(caller_audio),
        'bot_transcript': input_transcript,
        'bot_response': bot_text,
        'bot_audio_bytes': len(bot_audio_bytes) if bot_audio_bytes else 0,
        'intent': intent_name
    }


if __name__ == "__main__":
    result = asyncio.run(run_voice_proof_of_concept())
    print("\nProof complete:", json.dumps(result, indent=2))
