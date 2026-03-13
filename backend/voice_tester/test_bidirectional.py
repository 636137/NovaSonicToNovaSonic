#!/usr/bin/env python3
"""Demonstrate real bidirectional conversation with Lex bot."""
import boto3
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_lex_direct():
    """Direct Lex conversation to prove bidirectional works."""
    lex_runtime = boto3.client('lexv2-runtime', region_name='us-east-1')
    
    bot_id = 'XBM0II2LVX'  # TreasuryVoiceBot
    bot_alias_id = '3XYSFYN07K'  # TreasuryProd
    locale_id = 'en_US'
    session_id = str(uuid.uuid4())
    
    print('='*60)
    print('REAL BIDIRECTIONAL LEX CONVERSATION')
    print('Bot: TreasuryVoiceBot')
    print('='*60)
    print()
    
    messages = [
        'Hello',
        'I need help with a payment',
        'Check my balance',
    ]
    
    for msg in messages:
        print(f'USER: {msg}')
        try:
            response = lex_runtime.recognize_text(
                botId=bot_id,
                botAliasId=bot_alias_id,
                localeId=locale_id,
                sessionId=session_id,
                text=msg
            )
            
            for m in response.get('messages', []):
                content = m.get('content', '')
                print(f'BOT:  {content}')
            
            intent = response.get('sessionState', {}).get('intent', {})
            if intent:
                print(f'      (Intent: {intent.get("name", "?")})')
            print()
        except Exception as e:
            print(f'ERROR: {e}')
            break


def test_nova_sonic_bidirectional():
    """Test Nova Sonic bidirectional communication."""
    import asyncio
    from voice_tester.nova_sonic_client import NovaSonicVoiceClient, NovaSonicConfig
    
    print('='*60)
    print('NOVA SONIC BIDIRECTIONAL TEST')
    print('='*60)
    print()
    
    async def run_test():
        config = NovaSonicConfig(region='us-east-1')
        client = NovaSonicVoiceClient(config)
        
        client.set_persona({
            "name": "Survey Participant",
            "background": "Testing bidirectional communication",
            "attributes": {"speaking_rate": "normal", "patience": "high"}
        })
        
        received_responses = []
        
        def on_transcript(role, text):
            print(f'  [{role.upper()}]: {text}')
            received_responses.append({'role': role, 'text': text})
        
        def on_audio(audio_bytes):
            print(f'  [AUDIO]: {len(audio_bytes)} bytes received')
        
        client.on_transcript = on_transcript
        client.on_speech_output = on_audio
        
        print('Starting session...')
        await client.start_session()
        print('Session started!\n')
        
        # Simulate conversation
        test_messages = [
            "Hello, I'm calling to participate in the survey",
            "Yes, I consent to the survey",
            "English please",
        ]
        
        for msg in test_messages:
            print(f'SENDING: "{msg}"')
            await client.send_text_message(msg)
            await asyncio.sleep(3)  # Wait for response
            print()
        
        await client.end_session()
        
        print('='*60)
        print(f'Total responses received: {len(received_responses)}')
        return len(received_responses) > 0
    
    return asyncio.run(run_test())


if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 1: Direct Lex Conversation")
    print("="*60 + "\n")
    test_lex_direct()
    
    print("\n" + "="*60)
    print("TEST 2: Nova Sonic Bidirectional")
    print("="*60 + "\n")
    test_nova_sonic_bidirectional()
