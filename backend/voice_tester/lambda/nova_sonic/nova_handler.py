"""
Nova Sonic Lambda Handler

Unified speech-to-speech processing using Amazon Nova Sonic.
Replaces separate Transcribe/Polly/Bedrock calls with a single
efficient speech-to-speech model.

Nova Sonic provides:
- Real-time bidirectional audio streaming
- Natural conversational voice synthesis
- Low latency for interactive testing
- Integrated STT + response generation + TTS
"""
import json
import logging
import os
import base64
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import boto3

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# AWS Clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

# Environment
NOVA_SONIC_MODEL_ID = os.environ.get('NOVA_SONIC_MODEL_ID', 'amazon.nova-sonic-v1:0')
NOVA_SONIC_VOICE = os.environ.get('NOVA_SONIC_VOICE', 'tiffany')
CALL_STATE_TABLE = os.environ.get('CALL_STATE_TABLE', 'VoiceTestCallState')
RECORDINGS_BUCKET = os.environ.get('RECORDINGS_BUCKET', '')

# Voice configurations
VOICE_OPTIONS = {
    'tiffany': {'description': 'Natural female voice, good for general callers'},
    'matthew': {'description': 'Natural male voice'},
    'amy': {'description': 'British English female voice'}
}

# Audio settings
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_FORMAT = 'pcm'


class NovaSonicProcessor:
    """
    Processes voice interactions using Nova Sonic speech-to-speech model.
    """
    
    def __init__(self, voice_id: str = 'tiffany', sample_rate: int = DEFAULT_SAMPLE_RATE):
        self.voice_id = voice_id
        self.sample_rate = sample_rate
        self.model_id = NOVA_SONIC_MODEL_ID
        
    def transcribe(self, audio_data: bytes) -> str:
        """
        Transcribe audio to text using Nova Sonic.
        
        Args:
            audio_data: Raw PCM audio bytes
            
        Returns:
            Transcribed text
        """
        if not audio_data or len(audio_data) < 100:
            return ""
        
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        request_body = {
            "schemaVersion": "messages-v1",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "audio": {
                                "format": DEFAULT_FORMAT,
                                "sampleRate": self.sample_rate,
                                "data": audio_base64
                            }
                        }
                    ]
                }
            ],
            "inferenceConfig": {
                "maxTokens": 500,
                "temperature": 0.1  # Low temp for accurate transcription
            },
            "system": [
                {
                    "text": "Transcribe the audio accurately. Return only the transcribed text."
                }
            ]
        }
        
        try:
            response = bedrock_runtime.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body)
            )
            
            result = json.loads(response['body'].read())
            content = result.get('output', {}).get('message', {}).get('content', [])
            
            for item in content:
                if 'text' in item:
                    return item['text'].strip()
            
            return ""
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
    
    def synthesize(self, text: str) -> bytes:
        """
        Synthesize speech from text using Nova Sonic.
        
        Args:
            text: Text to speak
            
        Returns:
            Raw PCM audio bytes
        """
        if not text:
            return b''
        
        request_body = {
            "schemaVersion": "messages-v1",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": f"Speak the following naturally: {text}"
                        }
                    ]
                }
            ],
            "inferenceConfig": {
                "maxTokens": 100,
                "temperature": 0.7
            },
            "audioConfig": {
                "voice": {
                    "voiceId": self.voice_id
                },
                "outputFormat": {
                    "format": DEFAULT_FORMAT,
                    "sampleRate": self.sample_rate
                }
            },
            "system": [
                {
                    "text": "You are a voice synthesis assistant. Speak naturally."
                }
            ]
        }
        
        try:
            response = bedrock_runtime.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body)
            )
            
            result = json.loads(response['body'].read())
            content = result.get('output', {}).get('message', {}).get('content', [])
            
            for item in content:
                if 'audio' in item:
                    return base64.b64decode(item['audio'].get('data', ''))
            
            return b''
            
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            return b''
    
    def generate_response(
        self,
        system_audio: bytes,
        persona_prompt: str,
        intent: str,
        conversation_history: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Listen to system audio and generate appropriate caller response.
        
        This is the core speech-to-speech function:
        1. Transcribes what the system said
        2. Generates contextual response based on persona/intent
        3. Synthesizes natural speech output
        
        Args:
            system_audio: Audio from the system/bot (PCM bytes)
            persona_prompt: System prompt defining caller persona
            intent: What the caller should try to accomplish
            conversation_history: Previous conversation turns
            
        Returns:
            Dict with transcript, response_text, and response_audio
        """
        conversation_history = conversation_history or []
        
        # Step 1: Transcribe system audio
        system_text = self.transcribe(system_audio) if system_audio else ""
        logger.info(f"System said: {system_text}")
        
        # Step 2: Generate response with speech output
        response_text, response_audio = self._generate_spoken_response(
            system_text=system_text,
            persona_prompt=persona_prompt,
            intent=intent,
            conversation_history=conversation_history
        )
        
        return {
            'system_transcript': system_text,
            'response_text': response_text,
            'response_audio': base64.b64encode(response_audio).decode('utf-8') if response_audio else ''
        }
    
    def _generate_spoken_response(
        self,
        system_text: str,
        persona_prompt: str,
        intent: str,
        conversation_history: List[Dict]
    ) -> tuple[str, bytes]:
        """Generate conversational response with speech"""
        
        # Build conversation context
        history_text = ""
        for turn in conversation_history[-6:]:
            role = "SYSTEM" if turn.get('role') in ['system', 'assistant'] else "YOU"
            history_text += f"{role}: {turn.get('content', '')}\n"
        
        user_prompt = f"""CONVERSATION SO FAR:
{history_text}

SYSTEM JUST SAID: {system_text}

YOUR INTENT: {intent}

Respond naturally as if speaking on the phone. Keep it brief (1-2 sentences).
Only output the words you would say."""

        request_body = {
            "schemaVersion": "messages-v1",
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user_prompt}]
                }
            ],
            "inferenceConfig": {
                "maxTokens": 200,
                "temperature": 0.7
            },
            "audioConfig": {
                "voice": {
                    "voiceId": self.voice_id
                },
                "outputFormat": {
                    "format": DEFAULT_FORMAT,
                    "sampleRate": self.sample_rate
                }
            },
            "system": [{"text": persona_prompt}] if persona_prompt else []
        }
        
        try:
            response = bedrock_runtime.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body)
            )
            
            result = json.loads(response['body'].read())
            content = result.get('output', {}).get('message', {}).get('content', [])
            
            response_text = ""
            response_audio = b''
            
            for item in content:
                if 'text' in item:
                    response_text = self._clean_response(item['text'])
                if 'audio' in item:
                    response_audio = base64.b64decode(item['audio'].get('data', ''))
            
            # If no audio returned, synthesize it
            if response_text and not response_audio:
                response_audio = self.synthesize(response_text)
            
            logger.info(f"Caller response: {response_text}")
            return response_text, response_audio
            
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            fallback = "Yes"
            return fallback, self.synthesize(fallback)
    
    def _clean_response(self, text: str) -> str:
        """Clean AI-generated response"""
        text = text.strip()
        
        # Remove quotes
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        
        # Remove role prefixes
        prefixes = ['YOU:', 'Caller:', 'Response:', 'I say:', '[Say]:', 'CALLER:']
        for prefix in prefixes:
            if text.upper().startswith(prefix.upper()):
                text = text[len(prefix):].strip()
        
        return text


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main Lambda handler for Nova Sonic voice processing.
    
    Operations:
    - transcribe: Convert audio to text
    - synthesize: Convert text to speech
    - respond: Full speech-to-speech (listen, think, speak)
    - process_turn: Process a conversation turn
    """
    operation = event.get('operation', 'respond')
    
    logger.info(f"Nova Sonic handler - operation: {operation}")
    
    # Get voice configuration
    voice_id = event.get('voice_id', os.environ.get('NOVA_SONIC_VOICE', 'tiffany'))
    sample_rate = event.get('sample_rate', DEFAULT_SAMPLE_RATE)
    
    processor = NovaSonicProcessor(voice_id=voice_id, sample_rate=sample_rate)
    
    try:
        if operation == 'transcribe':
            return handle_transcribe(event, processor)
        elif operation == 'synthesize':
            return handle_synthesize(event, processor)
        elif operation == 'respond':
            return handle_respond(event, processor)
        elif operation == 'process_turn':
            return handle_process_turn(event, processor)
        else:
            return {
                'statusCode': 400,
                'error': f'Unknown operation: {operation}'
            }
    except Exception as e:
        logger.error(f"Error in Nova Sonic handler: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e)
        }


def handle_transcribe(event: Dict[str, Any], processor: NovaSonicProcessor) -> Dict:
    """Transcribe audio to text"""
    
    audio_base64 = event.get('audio_data', '')
    if not audio_base64:
        return {'statusCode': 400, 'error': 'audio_data required'}
    
    audio_data = base64.b64decode(audio_base64)
    transcript = processor.transcribe(audio_data)
    
    return {
        'statusCode': 200,
        'transcript': transcript
    }


def handle_synthesize(event: Dict[str, Any], processor: NovaSonicProcessor) -> Dict:
    """Synthesize text to speech"""
    
    text = event.get('text', '')
    if not text:
        return {'statusCode': 400, 'error': 'text required'}
    
    audio_data = processor.synthesize(text)
    
    return {
        'statusCode': 200,
        'audio_data': base64.b64encode(audio_data).decode('utf-8'),
        'sample_rate': processor.sample_rate,
        'format': DEFAULT_FORMAT
    }


def handle_respond(event: Dict[str, Any], processor: NovaSonicProcessor) -> Dict:
    """Full speech-to-speech response generation"""
    
    system_audio_base64 = event.get('system_audio', '')
    system_audio = base64.b64decode(system_audio_base64) if system_audio_base64 else b''
    
    persona = event.get('persona', {})
    persona_prompt = build_persona_prompt(persona)
    
    intent = event.get('intent', 'Respond naturally to the system')
    conversation_history = event.get('conversation_history', [])
    
    result = processor.generate_response(
        system_audio=system_audio,
        persona_prompt=persona_prompt,
        intent=intent,
        conversation_history=conversation_history
    )
    
    return {
        'statusCode': 200,
        **result
    }


def handle_process_turn(event: Dict[str, Any], processor: NovaSonicProcessor) -> Dict:
    """Process a full conversation turn with state management"""
    
    call_id = event.get('call_id', '')
    step_id = event.get('step_id', '')
    
    # Get current state from DynamoDB
    call_state = get_call_state(call_id) if call_id else {}
    
    # Process the turn
    system_audio_base64 = event.get('system_audio', '')
    system_audio = base64.b64decode(system_audio_base64) if system_audio_base64 else b''
    
    persona = event.get('persona', call_state.get('persona', {}))
    persona_prompt = build_persona_prompt(persona)
    
    intent = event.get('intent', '')
    conversation_history = call_state.get('conversation_history', [])
    
    # Generate response
    result = processor.generate_response(
        system_audio=system_audio,
        persona_prompt=persona_prompt,
        intent=intent,
        conversation_history=conversation_history
    )
    
    # Update state
    new_turns = [
        {
            'role': 'system',
            'content': result['system_transcript'],
            'timestamp': datetime.now(timezone.utc).isoformat()
        },
        {
            'role': 'caller',
            'content': result['response_text'],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    ]
    conversation_history.extend(new_turns)
    
    if call_id:
        update_call_state(call_id, {
            'conversation_history': conversation_history,
            'last_step': step_id,
            'updated_at': datetime.now(timezone.utc).isoformat()
        })
    
    return {
        'statusCode': 200,
        'step_id': step_id,
        'system_said': result['system_transcript'],
        'caller_said': result['response_text'],
        'caller_audio': result['response_audio']
    }


def build_persona_prompt(persona: Dict) -> str:
    """Build system prompt from persona configuration"""
    
    if not persona:
        return """You are a phone caller testing an automated system. 
Respond naturally and briefly. Keep responses to 1-2 sentences.
Only say what you would actually speak - no descriptions or actions."""
    
    name = persona.get('name', 'Test Caller')
    background = persona.get('background', '')
    attributes = persona.get('attributes', {})
    
    speaking_rate = attributes.get('speaking_rate', 'normal')
    patience = attributes.get('patience', 'normal')
    clarity = attributes.get('clarity', 'clear')
    
    return f"""You are playing the role of a phone caller named {name}.

BACKGROUND: {background}

SPEAKING STYLE:
- Pace: {speaking_rate}
- Patience: {patience}  
- Clarity: {clarity}

RULES:
1. Respond as if on an actual phone call - brief and natural
2. Only say what you would actually speak aloud
3. Keep responses to 1-2 sentences
4. Answer questions directly
5. Stay in character throughout"""


def get_call_state(call_id: str) -> Dict:
    """Get call state from DynamoDB"""
    try:
        table = dynamodb.Table(CALL_STATE_TABLE)
        response = table.get_item(Key={'call_id': call_id})
        return response.get('Item', {})
    except Exception as e:
        logger.error(f"Error getting call state: {e}")
        return {}


def update_call_state(call_id: str, updates: Dict):
    """Update call state in DynamoDB"""
    try:
        table = dynamodb.Table(CALL_STATE_TABLE)
        table.update_item(
            Key={'call_id': call_id},
            UpdateExpression='SET ' + ', '.join(f'#{k} = :{k}' for k in updates.keys()),
            ExpressionAttributeNames={f'#{k}': k for k in updates.keys()},
            ExpressionAttributeValues={f':{k}': v for k, v in updates.items()}
        )
    except Exception as e:
        logger.error(f"Error updating call state: {e}")
