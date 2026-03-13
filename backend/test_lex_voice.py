#!/usr/bin/env python3
"""Test Lex voice recognition directly."""
import boto3

lex = boto3.client('lexv2-runtime', region_name='us-east-1')
polly = boto3.client('polly', region_name='us-east-1')

# Generate test audio
print('Generating test audio...')
response = polly.synthesize_speech(
    Text='Hello',
    OutputFormat='pcm',
    SampleRate='16000',
    VoiceId='Matthew',
    Engine='neural'
)
audio = response['AudioStream'].read()
print(f'Generated {len(audio)} bytes of audio')

# Test each bot
bots_to_test = [
    ('CensusSurveyBot', 'JFJLA39AXI', 'TSTALIASID'),
    ('CensusEnumeratorBot', 'IWSQ3TLK3B', 'TSTALIASID'),
]

for bot_name, bot_id, alias_id in bots_to_test:
    print(f'\nTesting {bot_name}...')
    try:
        resp = lex.recognize_utterance(
            botId=bot_id,
            botAliasId=alias_id,
            localeId='en_US',
            sessionId=f'voice-test-{bot_id}',
            requestContentType='audio/l16; rate=16000; channels=1',
            responseContentType='audio/pcm',
            inputStream=audio
        )
        print(f'  SUCCESS!')
        print(f'  Input transcript: {resp.get("inputTranscript", "(none)")}')
        if 'audioStream' in resp:
            audio_out = resp['audioStream'].read()
            print(f'  Response audio: {len(audio_out)} bytes')
        else:
            print('  No audio response')
    except Exception as e:
        print(f'  ERROR: {e}')
