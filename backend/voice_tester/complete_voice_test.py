#!/usr/bin/env python3
"""
Complete Real Voice Test with Nova Sonic

This test properly demonstrates:
1. Real audio sent to Lex (not text)
2. Real audio received from Lex
3. Nova Sonic processing bidirectionally
4. Proper decoding of Lex responses
"""
import asyncio
import base64
import gzip
import json
import logging
import os
import sys
import uuid
import wave
import struct
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import boto3

sys.path.insert(0, str(Path(__file__).parent))
from nova_sonic_client import NovaSonicVoiceClient, NovaSonicConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def decode_lex_response(data: str) -> str:
    """Decode base64+gzip Lex response."""
    if not data:
        return ""
    try:
        # Try base64 + gzip decode
        decoded = base64.b64decode(data)
        decompressed = gzip.decompress(decoded)
        return decompressed.decode('utf-8')
    except Exception:
        # If that fails, return as-is
        return data


class RealVoiceTester:
    """Real voice tester using Nova Sonic for bidirectional speech."""
    
    def __init__(
        self,
        bot_id: str = 'XBM0II2LVX',
        bot_alias_id: str = 'TSTALIASID',
        locale_id: str = 'en_US',
        region: str = 'us-east-1'
    ):
        self.bot_id = bot_id
        self.bot_alias_id = bot_alias_id
        self.locale_id = locale_id
        self.region = region
        
        self.lex_runtime = boto3.client('lexv2-runtime', region_name=region)
        self.polly = boto3.client('polly', region_name=region)
        
        # Nova Sonic
        self.nova_config = NovaSonicConfig(region=region)
        self.nova_client = NovaSonicVoiceClient(self.nova_config)
        
        self.session_id = str(uuid.uuid4())
        self.conversation: List[Dict] = []
        
    def generate_audio(self, text: str) -> bytes:
        """Generate audio using Polly."""
        response = self.polly.synthesize_speech(
            Text=text,
            OutputFormat='pcm',
            SampleRate='16000',
            VoiceId='Matthew',
            Engine='neural'
        )
        return response['AudioStream'].read()
        
    def send_audio_to_lex(self, audio: bytes) -> Dict[str, Any]:
        """Send audio to Lex and get response."""
        response = self.lex_runtime.recognize_utterance(
            botId=self.bot_id,
            botAliasId=self.bot_alias_id,
            localeId=self.locale_id,
            sessionId=self.session_id,
            requestContentType='audio/l16; rate=16000; channels=1',
            responseContentType='audio/pcm',
            inputStream=audio
        )
        
        # Get audio response
        audio_out = None
        if 'audioStream' in response:
            audio_out = response['audioStream'].read()
            
        # Decode transcript (base64 + gzip)
        input_transcript = decode_lex_response(
            response.get('inputTranscript', '')
        )
        
        # Decode messages
        messages_raw = response.get('messages', '')
        if messages_raw:
            messages_decoded = decode_lex_response(messages_raw)
            try:
                messages = json.loads(messages_decoded)
            except:
                messages = [{'content': messages_decoded}]
        else:
            messages = []
            
        # Get session state
        session_state_raw = response.get('sessionState', '')
        if session_state_raw:
            session_decoded = decode_lex_response(session_state_raw)
            try:
                session_state = json.loads(session_decoded)
            except:
                session_state = {}
        else:
            session_state = {}
            
        return {
            'audio': audio_out,
            'input_transcript': input_transcript,
            'messages': messages,
            'session_state': session_state,
            'intent': session_state.get('intent', {}).get('name', ''),
            'dialog': session_state.get('dialogAction', {}).get('type', '')
        }
        
    async def start_nova_sonic(self):
        """Start Nova Sonic session."""
        await self.nova_client.start_session()
        logger.info("Nova Sonic session started")
        
    async def stop_nova_sonic(self):
        """Stop Nova Sonic session."""
        await self.nova_client.end_session()
        logger.info("Nova Sonic session ended")
        
    async def process_audio_through_nova(self, lex_audio: bytes) -> bytes:
        """
        Send Lex's audio to Nova Sonic and get Nova's response.
        
        This is the bidirectional part:
        - Nova LISTENS to what Lex said
        - Nova GENERATES a spoken response
        """
        if not lex_audio:
            return b''
            
        logger.info(f"Sending {len(lex_audio)} bytes to Nova Sonic")
        
        # Start audio input
        await self.nova_client.start_audio_input()
        
        # Stream audio in chunks
        chunk_size = 4096
        for i in range(0, len(lex_audio), chunk_size):
            chunk = lex_audio[i:i+chunk_size]
            await self.nova_client.send_audio_chunk(chunk)
            await asyncio.sleep(0.01)  # Small delay between chunks
            
        # End audio input
        await self.nova_client.end_audio_input()
        
        # Wait for response
        await asyncio.sleep(3.0)
        
        # Collect output audio
        output = bytearray()
        while not self.nova_client.audio_queue.empty():
            chunk = await self.nova_client.get_audio_output()
            if chunk:
                output.extend(chunk)
                
        if output:
            logger.info(f"Nova Sonic generated {len(output)} bytes of audio")
        else:
            logger.warning("Nova Sonic did not generate audio")
            
        return bytes(output)
        
    async def run_conversation(
        self,
        initial_text: str = "Hello",
        max_turns: int = 5
    ):
        """Run a complete voice conversation."""
        print("=" * 70)
        print("REAL VOICE CONVERSATION WITH NOVA SONIC")
        print("=" * 70)
        print(f"Bot: TreasuryVoiceBot ({self.bot_id})")
        print(f"Session: {self.session_id}")
        print()
        
        await self.start_nova_sonic()
        
        try:
            # Generate initial audio
            print(f'[CALLER] "{initial_text}"')
            caller_audio = self.generate_audio(initial_text)
            print(f'         Generated {len(caller_audio)} bytes of audio')
            
            for turn in range(max_turns):
                print(f"\n--- Turn {turn + 1} ---")
                
                # Send to Lex
                print(f"[→ LEX] Sending {len(caller_audio)} bytes...")
                lex_response = self.send_audio_to_lex(caller_audio)
                
                # What Lex heard
                input_transcript = lex_response['input_transcript']
                print(f"[LEX HEARD] \"{input_transcript}\"")
                
                self.conversation.append({
                    'turn': turn + 1,
                    'speaker': 'caller',
                    'text': input_transcript,
                    'audio_bytes': len(caller_audio)
                })
                
                # What Lex said
                lex_audio = lex_response['audio']
                intent = lex_response['intent']
                dialog = lex_response['dialog']
                
                bot_text = ''
                for msg in lex_response.get('messages', []):
                    if isinstance(msg, dict) and msg.get('content'):
                        bot_text = msg['content']
                        break
                        
                print(f"[LEX SAYS] \"{bot_text}\" (Intent: {intent})")
                print(f"           Audio: {len(lex_audio) if lex_audio else 0} bytes")
                
                if bot_text or lex_audio:
                    self.conversation.append({
                        'turn': turn + 1,
                        'speaker': 'bot',
                        'text': bot_text,
                        'intent': intent,
                        'audio_bytes': len(lex_audio) if lex_audio else 0
                    })
                    
                # Check if done
                if dialog == 'Close':
                    print("\n[CONVERSATION ENDED BY BOT]")
                    break
                    
                if not lex_audio:
                    print("[WARNING] No audio from Lex")
                    break
                    
                # Process through Nova Sonic
                print(f"\n[→ NOVA SONIC] Processing Lex audio...")
                nova_audio = await self.process_audio_through_nova(lex_audio)
                
                if nova_audio:
                    print(f"[NOVA SONIC →] Generated {len(nova_audio)} bytes response")
                    caller_audio = nova_audio
                else:
                    # Fallback: generate simple response
                    print("[NOVA SONIC] No response, using fallback")
                    # Generate a contextual response
                    if 'balance' in bot_text.lower():
                        fallback_text = "Yes, I want to check my balance"
                    elif 'account' in bot_text.lower():
                        fallback_text = "My account number is 12345"
                    else:
                        fallback_text = "Yes"
                    print(f'[FALLBACK] "{fallback_text}"')
                    caller_audio = self.generate_audio(fallback_text)
                    
        finally:
            await self.stop_nova_sonic()
            
        # Summary
        print("\n" + "=" * 70)
        print("CONVERSATION SUMMARY")
        print("=" * 70)
        
        for entry in self.conversation:
            speaker = entry['speaker'].upper()
            text = entry.get('text', '(audio only)')
            audio_bytes = entry.get('audio_bytes', 0)
            intent = entry.get('intent', '')
            
            if speaker == 'CALLER':
                print(f"[CALLER] \"{text}\" ({audio_bytes} bytes)")
            else:
                print(f"[BOT]    \"{text}\" ({audio_bytes} bytes) [Intent: {intent}]")
                
        return self.conversation


async def main():
    tester = RealVoiceTester(
        bot_id='XBM0II2LVX',
        bot_alias_id='TSTALIASID',
        locale_id='en_US',
        region='us-east-1'
    )
    
    # Set persona for Nova Sonic
    tester.nova_client.set_persona({
        "name": "Test Caller",
        "background": "A customer testing the voice system",
        "attributes": {
            "speaking_rate": "normal",
            "patience": "high"
        }
    })
    
    conversation = await tester.run_conversation(
        initial_text="I have a question about my refund",
        max_turns=5
    )
    
    print(f"\nCompleted {len(conversation)} conversation turns")


if __name__ == "__main__":
    asyncio.run(main())
