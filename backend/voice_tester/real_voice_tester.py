#!/usr/bin/env python3
"""
Real Voice Call Tester with Nova Sonic

Makes actual voice calls to Amazon Connect using Nova Sonic for
bidirectional speech-to-speech communication.

This is NOT a simulation - it uses real audio streaming.
"""
import asyncio
import base64
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

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from voice_tester.nova_sonic_client import NovaSonicVoiceClient, NovaSonicConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RealVoiceCallTester:
    """
    Makes REAL voice calls using Nova Sonic for speech-to-speech.
    
    Flow:
    1. Call Connect via Lex voice API (recognize_utterance)
    2. Send audio from Nova Sonic TO Lex
    3. Receive audio from Lex 
    4. Send that TO Nova Sonic for understanding
    5. Nova Sonic generates response audio
    6. Send that BACK to Lex
    7. Repeat until conversation complete
    """
    
    def __init__(
        self,
        bot_id: str,
        bot_alias_id: str,
        locale_id: str = "en_US",
        region: str = "us-east-1"
    ):
        self.bot_id = bot_id
        self.bot_alias_id = bot_alias_id
        self.locale_id = locale_id
        self.region = region
        
        # Lex V2 runtime for voice
        self.lex_runtime = boto3.client('lexv2-runtime', region_name=region)
        
        # Nova Sonic client
        self.nova_config = NovaSonicConfig(region=region)
        self.nova_client = NovaSonicVoiceClient(self.nova_config)
        
        # Session tracking
        self.session_id = str(uuid.uuid4())
        self.conversation_history: List[Dict] = []
        
        # Audio settings
        self.sample_rate = 16000  # 16kHz for Lex
        self.channels = 1
        self.sample_width = 2  # 16-bit
        
    def set_persona(self, persona: Dict[str, Any]):
        """Set the AI caller persona."""
        self.nova_client.set_persona(persona)
        
    async def start_conversation(self):
        """Start Nova Sonic session."""
        await self.nova_client.start_session()
        logger.info("Nova Sonic session started for voice call")
        
    async def end_conversation(self):
        """End Nova Sonic session."""
        await self.nova_client.end_session()
        logger.info("Nova Sonic session ended")
        
    def _generate_greeting_audio(self, text: str) -> bytes:
        """
        Generate initial greeting audio using Polly (for first turn).
        Nova Sonic needs to hear something first to respond.
        """
        polly = boto3.client('polly', region_name=self.region)
        
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat='pcm',
            SampleRate=str(self.sample_rate),
            VoiceId='Matthew',
            Engine='neural'
        )
        
        return response['AudioStream'].read()
        
    def _send_audio_to_lex(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Send audio to Lex and get voice response.
        
        Uses recognize_utterance for REAL voice interaction.
        """
        # Lex expects audio/l16 format
        response = self.lex_runtime.recognize_utterance(
            botId=self.bot_id,
            botAliasId=self.bot_alias_id,
            localeId=self.locale_id,
            sessionId=self.session_id,
            requestContentType='audio/l16; rate=16000; channels=1',
            responseContentType='audio/pcm',
            inputStream=audio_bytes
        )
        
        # Get the audio response
        audio_response = None
        if 'audioStream' in response:
            audio_response = response['audioStream'].read()
            
        # Get transcript and intent
        messages = []
        input_transcript = response.get('inputTranscript', '')
        
        # Decode messages from response
        if 'messages' in response:
            msg_data = response['messages']
            if isinstance(msg_data, str):
                try:
                    messages = json.loads(msg_data)
                except:
                    messages = [{'content': msg_data}]
            else:
                messages = msg_data
                
        # Get session state
        session_state = {}
        if 'sessionState' in response:
            state_data = response['sessionState']
            if isinstance(state_data, str):
                try:
                    session_state = json.loads(state_data)
                except:
                    pass
            else:
                session_state = state_data
                
        intent_name = session_state.get('intent', {}).get('name', '')
        dialog_state = session_state.get('dialogAction', {}).get('type', '')
        
        return {
            'audio': audio_response,
            'input_transcript': input_transcript,
            'messages': messages,
            'intent': intent_name,
            'dialog_state': dialog_state,
            'session_state': session_state
        }
        
    async def _process_lex_audio_with_nova(self, lex_audio: bytes) -> bytes:
        """
        Process Lex's audio response through Nova Sonic.
        
        Nova Sonic listens to what Lex said and generates a response.
        """
        if not lex_audio:
            return b''
            
        # Send Lex audio to Nova Sonic for processing
        await self.nova_client.start_audio_input()
        
        # Send in chunks
        chunk_size = 1024
        for i in range(0, len(lex_audio), chunk_size):
            chunk = lex_audio[i:i+chunk_size]
            await self.nova_client.send_audio_chunk(chunk)
            await asyncio.sleep(0.01)
            
        await self.nova_client.end_audio_input()
        
        # Wait for Nova Sonic to process and respond
        await asyncio.sleep(2.0)
        
        # Collect response audio
        response_audio = bytearray()
        while not self.nova_client.audio_queue.empty():
            chunk = await self.nova_client.get_audio_output()
            if chunk:
                response_audio.extend(chunk)
                
        return bytes(response_audio)
        
    async def run_voice_conversation(
        self,
        initial_text: str = "Hello",
        max_turns: int = 10
    ) -> List[Dict]:
        """
        Run a complete voice conversation.
        
        Returns conversation history with transcripts and audio info.
        """
        print("="*60)
        print("REAL VOICE CONVERSATION")
        print(f"Bot: {self.bot_id}")
        print(f"Session: {self.session_id}")
        print("="*60)
        print()
        
        # Start Nova Sonic
        await self.start_conversation()
        
        try:
            # Generate initial greeting audio
            print(f"[CALLER] Generating initial greeting: '{initial_text}'")
            caller_audio = self._generate_greeting_audio(initial_text)
            print(f"[CALLER] Audio generated: {len(caller_audio)} bytes")
            
            for turn in range(max_turns):
                print(f"\n--- Turn {turn + 1} ---")
                
                # Send audio to Lex
                print(f"[CALLER -> LEX] Sending {len(caller_audio)} bytes of audio...")
                lex_response = self._send_audio_to_lex(caller_audio)
                
                # Log what Lex heard
                input_transcript = lex_response.get('input_transcript', '')
                if input_transcript:
                    print(f"[LEX HEARD] '{input_transcript}'")
                    self.conversation_history.append({
                        'turn': turn + 1,
                        'speaker': 'caller',
                        'transcript': input_transcript,
                        'audio_bytes': len(caller_audio),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                
                # Log Lex's response
                lex_audio = lex_response.get('audio')
                messages = lex_response.get('messages', [])
                intent = lex_response.get('intent', '')
                dialog_state = lex_response.get('dialog_state', '')
                
                lex_text = ''
                for msg in messages:
                    if isinstance(msg, dict):
                        lex_text = msg.get('content', '')
                    else:
                        lex_text = str(msg)
                    if lex_text:
                        break
                        
                if lex_text or lex_audio:
                    print(f"[LEX SAYS] '{lex_text}' (Intent: {intent})")
                    print(f"[LEX AUDIO] {len(lex_audio) if lex_audio else 0} bytes")
                    self.conversation_history.append({
                        'turn': turn + 1,
                        'speaker': 'bot',
                        'transcript': lex_text,
                        'intent': intent,
                        'dialog_state': dialog_state,
                        'audio_bytes': len(lex_audio) if lex_audio else 0,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    
                # Check if conversation should end
                if dialog_state in ['Close', 'Delegate'] and not lex_audio:
                    print("\n[END] Conversation completed")
                    break
                    
                if not lex_audio:
                    print("[WARNING] No audio from Lex, ending conversation")
                    break
                    
                # Process Lex audio through Nova Sonic
                print(f"[LEX -> NOVA SONIC] Processing {len(lex_audio)} bytes...")
                caller_audio = await self._process_lex_audio_with_nova(lex_audio)
                
                if caller_audio:
                    print(f"[NOVA SONIC RESPONSE] {len(caller_audio)} bytes of audio generated")
                else:
                    print("[NOVA SONIC] No response audio, using fallback")
                    # Fallback to simple response if Nova didn't respond
                    caller_audio = self._generate_greeting_audio("Yes")
                    
        finally:
            await self.end_conversation()
            
        print("\n" + "="*60)
        print("CONVERSATION SUMMARY")
        print("="*60)
        for entry in self.conversation_history:
            speaker = entry['speaker'].upper()
            transcript = entry.get('transcript', '')
            audio_bytes = entry.get('audio_bytes', 0)
            print(f"[{speaker}] {transcript} ({audio_bytes} bytes)")
            
        return self.conversation_history


async def main():
    """Run a real voice test."""
    # Use Treasury bot which has a built version
    # Note: Use DRAFT version for testing as it has latest build
    tester = RealVoiceCallTester(
        bot_id='XBM0II2LVX',  # TreasuryVoiceBot
        bot_alias_id='TSTALIASID',  # TestBotAlias (points to DRAFT)
        locale_id='en_US',
        region='us-east-1'
    )
    
    # Set AI caller persona
    tester.set_persona({
        "name": "Voice Test Caller",
        "background": "Testing voice system with real audio",
        "attributes": {
            "speaking_rate": "normal",
            "patience": "high"
        }
    })
    
    # Run conversation
    history = await tester.run_voice_conversation(
        initial_text="Hello, I need help with my account",
        max_turns=5
    )
    
    print(f"\nTotal turns: {len(history)}")
    

if __name__ == "__main__":
    asyncio.run(main())
