#!/usr/bin/env python3
"""Test TreasuryVoiceBot with real voice audio."""
import boto3
import json

lex = boto3.client('lexv2-runtime', region_name='us-east-1')
polly = boto3.client('polly', region_name='us-east-1')

# Generate test audio
print('Generating audio for: Hello, I need help')
response = polly.synthesize_speech(
    Text='Hello, I need help',
    OutputFormat='pcm',
    SampleRate='16000',
    VoiceId='Matthew',
    Engine='neural'
)
audio = response['AudioStream'].read()
print(f'Generated {len(audio)} bytes')

# Send to Treasury bot
print('\nSending to TreasuryVoiceBot...')
try:
    resp = lex.recognize_utterance(
        botId='XBM0II2LVX',
        botAliasId='3XYSFYN07K',
        localeId='en_US',
        sessionId='real-voice-test-002',
        requestContentType='audio/l16; rate=16000; channels=1',
        responseContentType='audio/pcm',
        inputStream=audio
    )
    
    print('SUCCESS!')
    print(f'Input transcript: {resp.get("inputTranscript", "(none)")}')
    
    if 'audioStream' in resp:
        audio_out = resp['audioStream'].read()
        print(f'Bot response audio: {len(audio_out)} bytes')
        
        # Save audio for verification
        with open('bot_response.pcm', 'wb') as f:
            f.write(audio_out)
        print('Saved response to bot_response.pcm')
    else:
        print('No audio response')
        
    if 'messages' in resp:
        msgs = resp['messages']
        if isinstance(msgs, str):
            msgs = json.loads(msgs)
        print(f'Bot messages: {msgs}')
        
except Exception as e:
    print(f'ERROR: {e}')
