#!/usr/bin/env python3
"""
Working Bidirectional Voice Tester for Amazon Connect

This tester demonstrates REAL bidirectional voice:
1. AI Caller speaks (via Polly) -> sent as audio to Lex
2. Lex bot responds with audio
3. AI Caller interprets response and replies

Uses:
- Amazon Polly for TTS (caller voice generation)
- Lex V2 recognize_utterance for real voice I/O
- Claude for response generation (decides what to say)

This proves real voice bidirectional communication even without
Nova Sonic. When Nova Sonic integration is complete, it can replace
the Polly+Claude combination for true speech-to-speech.
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
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def decode_lex_field(data: str) -> str:
    """Decode base64+gzip Lex response field."""
    if not data:
        return ""
    try:
        decoded = base64.b64decode(data)
        decompressed = gzip.decompress(decoded)
        return decompressed.decode('utf-8')
    except Exception:
        return data


class WorkingVoiceTester:
    """
    Working bidirectional voice tester for Amazon Connect.
    
    Uses real audio for all Lex communication.
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
        
        # AWS clients
        self.lex_runtime = boto3.client('lexv2-runtime', region_name=region)
        self.polly = boto3.client('polly', region_name=region)
        self.bedrock = boto3.client('bedrock-runtime', region_name=region)
        
        # Session ID
        self.session_id = str(uuid.uuid4())
        
        # Conversation tracking
        self.conversation: List[Dict[str, Any]] = []
        self.turn_count = 0
        
        # Persona
        self.persona = {
            "name": "Test Caller",
            "goal": "Test the voice system",
            "style": "polite and clear"
        }
        
        # Output directory for audio files
        self.output_dir = Path('/Users/ChadDHendren/AmazonConnect1/voice_output')
        self.output_dir.mkdir(exist_ok=True)
        
    def set_persona(self, persona: Dict[str, Any]):
        """Set the AI caller persona."""
        self.persona = persona
        
    def _generate_speech(self, text: str) -> bytes:
        """Generate speech audio using Amazon Polly."""
        response = self.polly.synthesize_speech(
            Text=text,
            OutputFormat='pcm',
            SampleRate='16000',
            VoiceId='Matthew',
            Engine='neural'
        )
        return response['AudioStream'].read()
        
    def _save_audio(self, audio: bytes, name: str, sample_rate: int = 16000):
        """Save audio to WAV file for verification."""
        path = self.output_dir / f"{name}.wav"
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(audio)
        return path
        
    def _send_audio_to_lex(self, audio: bytes) -> Dict[str, Any]:
        """Send audio to Lex and get voice response."""
        response = self.lex_runtime.recognize_utterance(
            botId=self.bot_id,
            botAliasId=self.bot_alias_id,
            localeId=self.locale_id,
            sessionId=self.session_id,
            requestContentType='audio/l16; rate=16000; channels=1',
            responseContentType='audio/pcm',
            inputStream=audio
        )
        
        # Extract audio response
        audio_response = None
        if 'audioStream' in response:
            audio_response = response['audioStream'].read()
            
        # Decode transcript
        input_transcript = decode_lex_field(response.get('inputTranscript', ''))
        
        # Decode messages
        messages_str = decode_lex_field(response.get('messages', ''))
        try:
            messages = json.loads(messages_str) if messages_str else []
        except:
            messages = [{"content": messages_str}] if messages_str else []
            
        # Extract bot text
        bot_text = ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get('content'):
                bot_text = msg['content']
                break
                
        # Decode session state
        state_str = decode_lex_field(response.get('sessionState', ''))
        try:
            session_state = json.loads(state_str) if state_str else {}
        except:
            session_state = {}
            
        intent = session_state.get('intent', {}).get('name', '')
        dialog_action = session_state.get('dialogAction', {}).get('type', '')
        
        return {
            'audio': audio_response,
            'input_transcript': input_transcript,
            'bot_text': bot_text,
            'intent': intent,
            'dialog_action': dialog_action,
            'session_state': session_state
        }
        
    def _generate_response(self, bot_message: str, conversation_context: str) -> str:
        """Use Claude to generate a contextual response for the caller."""
        
        prompt = f"""You are playing the role of a phone caller in a customer service test.

PERSONA:
- Name: {self.persona.get('name', 'Test Caller')}
- Goal: {self.persona.get('goal', 'Test the system')}
- Style: {self.persona.get('style', 'polite')}

CONVERSATION SO FAR:
{conversation_context}

BOT JUST SAID: "{bot_message}"

Generate a natural, brief response (1-2 sentences max) that continues the conversation.
Keep it conversational and realistic. Stay in character.

Response:"""

        response = self.bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            })
        )
        
        result = json.loads(response['body'].read())
        return result['content'][0]['text'].strip()
        
    async def run_conversation(
        self,
        initial_message: str,
        max_turns: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Run a complete voice conversation.
        
        Returns conversation history with all audio data info.
        """
        print("=" * 70)
        print("BIDIRECTIONAL VOICE CONVERSATION")
        print("=" * 70)
        print(f"Bot: {self.bot_id}")
        print(f"Session: {self.session_id}")
        print(f"Audio output: {self.output_dir}")
        print()
        
        # Generate initial caller audio
        caller_text = initial_message
        
        for turn in range(max_turns):
            self.turn_count += 1
            print(f"\n--- Turn {self.turn_count} ---")
            
            # Generate caller speech
            print(f'[CALLER] "{caller_text}"')
            caller_audio = self._generate_speech(caller_text)
            caller_path = self._save_audio(caller_audio, f"turn{self.turn_count}_caller")
            print(f"         Audio: {len(caller_audio)} bytes -> {caller_path.name}")
            
            # Record caller turn
            self.conversation.append({
                'turn': self.turn_count,
                'speaker': 'caller',
                'text': caller_text,
                'audio_bytes': len(caller_audio),
                'audio_file': str(caller_path),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
            # Send to Lex
            print(f"[→ LEX] Sending audio...")
            lex_response = self._send_audio_to_lex(caller_audio)
            
            # What did Lex hear?
            heard = lex_response['input_transcript']
            print(f"[LEX ←] Heard: \"{heard}\"")
            
            # What did Lex say?
            bot_text = lex_response['bot_text']
            bot_audio = lex_response['audio']
            intent = lex_response['intent']
            dialog = lex_response['dialog_action']
            
            if bot_text or bot_audio:
                print(f'[BOT] "{bot_text}" (Intent: {intent})')
                
                if bot_audio:
                    bot_path = self._save_audio(bot_audio, f"turn{self.turn_count}_bot")
                    print(f"      Audio: {len(bot_audio)} bytes -> {bot_path.name}")
                else:
                    bot_path = None
                    
                # Record bot turn
                self.conversation.append({
                    'turn': self.turn_count,
                    'speaker': 'bot',
                    'text': bot_text,
                    'intent': intent,
                    'dialog_action': dialog,
                    'audio_bytes': len(bot_audio) if bot_audio else 0,
                    'audio_file': str(bot_path) if bot_path else None,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
            
            # Check if conversation should end
            if dialog == 'Close':
                print("\n[END] Bot closed conversation")
                break
                
            if not bot_audio:
                print("[WARNING] No audio from bot")
                break
                
            # Generate response for next turn
            conversation_context = "\n".join([
                f"{'CALLER' if t['speaker']=='caller' else 'BOT'}: {t['text']}"
                for t in self.conversation[-6:]  # Last 3 turns
            ])
            
            print("\n[AI] Generating caller response...")
            caller_text = self._generate_response(bot_text, conversation_context)
            
        # Summary
        print("\n" + "=" * 70)
        print("CONVERSATION COMPLETE")
        print("=" * 70)
        
        print("\nTranscript:")
        for entry in self.conversation:
            speaker = entry['speaker'].upper()
            text = entry.get('text', '')
            audio = entry.get('audio_bytes', 0)
            
            if speaker == 'CALLER':
                print(f"  [CALLER] \"{text}\" ({audio} bytes)")
            else:
                intent = entry.get('intent', '')
                print(f"  [BOT]    \"{text}\" ({audio} bytes) [{intent}]")
                
        print(f"\nTotal turns: {len(self.conversation)}")
        print(f"Audio files in: {self.output_dir}")
        
        return self.conversation


async def main():
    """Run a demonstration voice conversation."""
    
    # Clean output directory
    output_dir = Path('/Users/ChadDHendren/AmazonConnect1/voice_output')
    for f in output_dir.glob('turn*.wav'):
        f.unlink()
    
    # Create tester
    tester = WorkingVoiceTester(
        bot_id='XBM0II2LVX',      # TreasuryVoiceBot
        bot_alias_id='TSTALIASID', # TestBotAlias
        locale_id='en_US',
        region='us-east-1'
    )
    
    # Set persona
    tester.set_persona({
        "name": "Sarah Johnson",
        "goal": "Ask about tax refund status",
        "style": "polite but direct"
    })
    
    # Run conversation
    conversation = await tester.run_conversation(
        initial_message="Hello, I have a question about my tax refund",
        max_turns=5
    )
    
    # Save conversation log
    log_path = output_dir / "conversation_log.json"
    with open(log_path, 'w') as f:
        json.dump(conversation, f, indent=2)
    print(f"\nConversation log: {log_path}")
    
    return conversation


if __name__ == "__main__":
    asyncio.run(main())
