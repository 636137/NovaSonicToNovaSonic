#!/usr/bin/env python3
"""Working Bidirectional Voice Tester for Amazon Connect"""
import asyncio
import base64
import gzip
import json
import logging
import uuid
import wave
from pathlib import Path
from datetime import datetime, timezone

import boto3

logging.basicConfig(level=logging.INFO)


def decode_lex_field(data):
    if not data:
        return ""
    try:
        decoded = base64.b64decode(data)
        decompressed = gzip.decompress(decoded)
        return decompressed.decode('utf-8')
    except:
        return data


class BidirectionalVoiceTester:
    def __init__(self, bot_id, bot_alias_id, locale_id="en_US", region="us-east-1"):
        self.bot_id = bot_id
        self.bot_alias_id = bot_alias_id
        self.locale_id = locale_id
        self.region = region
        self.lex_runtime = boto3.client('lexv2-runtime', region_name=region)
        self.polly = boto3.client('polly', region_name=region)
        self.bedrock = boto3.client('bedrock-runtime', region_name=region)
        self.session_id = str(uuid.uuid4())
        self.conversation = []
        self.turn_count = 0
        self.persona = {"name": "Caller", "goal": "Test", "style": "polite"}
        self.output_dir = Path('/Users/ChadDHendren/AmazonConnect1/voice_output')
        self.output_dir.mkdir(exist_ok=True)

    def set_persona(self, persona):
        self.persona = persona

    def generate_speech(self, text):
        response = self.polly.synthesize_speech(
            Text=text, OutputFormat='pcm', SampleRate='16000',
            VoiceId='Matthew', Engine='neural'
        )
        return response['AudioStream'].read()

    def save_audio(self, audio, name, sample_rate=16000):
        path = self.output_dir / f"{name}.wav"
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(audio)
        return path

    def send_audio_to_lex(self, audio):
        response = self.lex_runtime.recognize_utterance(
            botId=self.bot_id, botAliasId=self.bot_alias_id,
            localeId=self.locale_id, sessionId=self.session_id,
            requestContentType='audio/l16; rate=16000; channels=1',
            responseContentType='audio/pcm', inputStream=audio
        )
        audio_response = response.get('audioStream')
        if audio_response:
            audio_response = audio_response.read()
        input_transcript = decode_lex_field(response.get('inputTranscript', ''))
        messages_str = decode_lex_field(response.get('messages', ''))
        try:
            messages = json.loads(messages_str) if messages_str else []
        except:
            messages = [{"content": messages_str}] if messages_str else []
        bot_text = ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get('content'):
                bot_text = msg['content']
                break
        state_str = decode_lex_field(response.get('sessionState', ''))
        try:
            session_state = json.loads(state_str) if state_str else {}
        except:
            session_state = {}
        intent = session_state.get('intent', {}).get('name', '')
        dialog_action = session_state.get('dialogAction', {}).get('type', '')
        return {'audio': audio_response, 'input_transcript': input_transcript,
                'bot_text': bot_text, 'intent': intent, 'dialog_action': dialog_action}

    def generate_response(self, bot_message, conversation_context):
        prompt = f'''Persona: {self.persona}.
Bot said: "{bot_message}"
Context: {conversation_context}
Generate a brief natural response (1-2 sentences).'''
        response = self.bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        result = json.loads(response['body'].read())
        return result['content'][0]['text'].strip()

    async def run_conversation(self, initial_message, max_turns=10):
        print("=" * 70)
        print("BIDIRECTIONAL VOICE CONVERSATION")
        print("=" * 70)
        print(f"Bot: {self.bot_id}")
        print(f"Session: {self.session_id}")
        print()
        caller_text = initial_message
        for turn in range(max_turns):
            self.turn_count += 1
            print(f"\n--- Turn {self.turn_count} ---")
            print(f'[CALLER] "{caller_text}"')
            caller_audio = self.generate_speech(caller_text)
            caller_path = self.save_audio(caller_audio, f"turn{self.turn_count}_caller")
            print(f"         Audio: {len(caller_audio)} bytes -> {caller_path.name}")
            self.conversation.append({
                'turn': self.turn_count, 'speaker': 'caller',
                'text': caller_text, 'audio_bytes': len(caller_audio)
            })
            print("[-> LEX] Sending audio...")
            lex_response = self.send_audio_to_lex(caller_audio)
            heard = lex_response['input_transcript']
            print(f'[LEX <-] Heard: "{heard}"')
            bot_text = lex_response['bot_text']
            bot_audio = lex_response['audio']
            intent = lex_response['intent']
            dialog = lex_response['dialog_action']
            if bot_text or bot_audio:
                print(f'[BOT] "{bot_text}" (Intent: {intent})')
                if bot_audio:
                    bot_path = self.save_audio(bot_audio, f"turn{self.turn_count}_bot")
                    print(f"      Audio: {len(bot_audio)} bytes -> {bot_path.name}")
                self.conversation.append({
                    'turn': self.turn_count, 'speaker': 'bot',
                    'text': bot_text, 'intent': intent,
                    'audio_bytes': len(bot_audio) if bot_audio else 0
                })
            if dialog == 'Close':
                print("\n[END] Bot closed conversation")
                break
            if not bot_audio:
                print("[WARNING] No audio from bot")
                break
            context = "\n".join([f"{'CALLER' if t['speaker']=='caller' else 'BOT'}: {t['text']}" for t in self.conversation[-6:]])
            print("\n[AI] Generating response...")
            caller_text = self.generate_response(bot_text, context)
        print("\n" + "=" * 70)
        print("CONVERSATION COMPLETE")
        print("=" * 70)
        for entry in self.conversation:
            speaker = entry['speaker'].upper()
            text = entry.get('text', '')
            audio = entry.get('audio_bytes', 0)
            if speaker == 'CALLER':
                print(f'  [CALLER] "{text}" ({audio} bytes)')
            else:
                print(f"  [BOT]    \"{text}\" ({audio} bytes) [{entry.get('intent', '')}]")
        return self.conversation


async def main():
    output_dir = Path('/Users/ChadDHendren/AmazonConnect1/voice_output')
    for f in output_dir.glob('turn*.wav'):
        f.unlink()
    tester = BidirectionalVoiceTester(
        bot_id='XBM0II2LVX', bot_alias_id='TSTALIASID',
        locale_id='en_US', region='us-east-1'
    )
    tester.set_persona({"name": "Sarah", "goal": "Ask about tax refund", "style": "polite"})
    return await tester.run_conversation("I have a question about my tax refund", max_turns=5)


if __name__ == "__main__":
    asyncio.run(main())
