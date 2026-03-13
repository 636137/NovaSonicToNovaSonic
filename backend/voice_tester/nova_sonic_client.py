"""
Amazon Nova Sonic Client for Voice Testing

Uses Amazon Nova Sonic (nova-sonic-v1:0) for realistic speech-to-speech
voice emulation with bidirectional streaming via the Smithy SDK.

Requires Python 3.12+ and: pip install aws-sdk-bedrock-runtime smithy-aws-core
"""
import asyncio
import base64
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, AsyncGenerator

from aws_sdk_bedrock_runtime.client import (
    BedrockRuntimeClient,
    InvokeModelWithBidirectionalStreamOperationInput
)
from aws_sdk_bedrock_runtime.models import (
    InvokeModelWithBidirectionalStreamInputChunk,
    BidirectionalInputPayloadPart
)
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)


@dataclass
class NovaSonicConfig:
    """Configuration for Amazon Nova Sonic"""
    model_id: str = "amazon.nova-sonic-v1:0"
    region: str = "us-east-1"
    
    # Voice settings
    voice_id: str = "matthew"  # Available: tiffany, matthew, amy
    
    # Audio settings (must match WebRTC audio)
    input_sample_rate: int = 16000   # 16kHz for input
    output_sample_rate: int = 24000  # 24kHz for Nova Sonic output
    channels: int = 1
    sample_bits: int = 16
    
    # Conversation settings
    system_prompt: str = ""
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 1024


@dataclass
class ConversationTurn:
    """A single turn in the conversation"""
    role: str  # 'user' or 'assistant'
    content: str  # Text content
    audio_data: Optional[bytes] = None
    timestamp: Optional[datetime] = None


class NovaSonicVoiceClient:
    """
    Client for Amazon Nova Sonic speech-to-speech model.
    
    Provides bidirectional streaming for realistic voice conversations.
    The AI caller can listen (STT) and speak (TTS) naturally.
    """
    
    def __init__(self, config: NovaSonicConfig = None):
        self.config = config or NovaSonicConfig()
        self.client: Optional[BedrockRuntimeClient] = None
        self.stream = None
        self.response_task = None
        self.is_active = False
        
        # Unique IDs for this session
        self.session_id = str(uuid.uuid4())
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        
        # Conversation state
        self.conversation_history: List[ConversationTurn] = []
        self.current_role = None
        self.display_assistant_text = False
        
        # Audio output queue
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        
        # Transcript accumulator
        self._current_transcript = ""
        
        # Callbacks
        self.on_transcript: Optional[Callable[[str, str], None]] = None  # (role, text)
        self.on_speech_output: Optional[Callable[[bytes], None]] = None
        self.on_turn_complete: Optional[Callable[[ConversationTurn], None]] = None
        
    def _initialize_client(self):
        """Initialize the Bedrock client with Smithy SDK."""
        # Get credentials from boto3 session (reads ~/.aws/credentials)
        import boto3
        session = boto3.Session()
        credentials = session.get_credentials()
        if credentials:
            frozen_credentials = credentials.get_frozen_credentials()
            os.environ['AWS_ACCESS_KEY_ID'] = frozen_credentials.access_key
            os.environ['AWS_SECRET_ACCESS_KEY'] = frozen_credentials.secret_key
            if frozen_credentials.token:
                os.environ['AWS_SESSION_TOKEN'] = frozen_credentials.token
            logger.info("Loaded AWS credentials from boto3 session")
        
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.config.region}.amazonaws.com",
            region=self.config.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        self.client = BedrockRuntimeClient(config=config)
        logger.info(f"Initialized Nova Sonic client for region {self.config.region}")
        
    async def _send_event(self, event_json: str):
        """Send an event to the bidirectional stream."""
        if not self.stream:
            raise RuntimeError("Stream not initialized")
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        await self.stream.input_stream.send(event)
        
    def set_persona(self, persona: Dict[str, Any]):
        """Set the AI caller's persona for the conversation"""
        persona_name = persona.get('name', 'Standard Caller')
        background = persona.get('background', '')
        attributes = persona.get('attributes', {})
        
        speaking_rate = attributes.get('speaking_rate', 'normal')
        patience = attributes.get('patience', 'normal')
        
        self.config.system_prompt = f"""You are playing the role of a phone caller in a customer service test scenario.

PERSONA: {persona_name}

BACKGROUND: {background}

SPEAKING STYLE:
- Speaking rate: {speaking_rate}
- Patience level: {patience}
- Speak naturally as if on a real phone call
- Keep responses brief and conversational (1-3 sentences max)
- Stay in character throughout the call
- Listen carefully to the automated prompts and respond appropriately

You are calling to test an automated phone system. Respond naturally to menus and prompts."""
        
    async def start_session(self):
        """Start a new bidirectional streaming session with Nova Sonic."""
        if not self.client:
            self._initialize_client()
            
        # Start the bidirectional stream
        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.config.model_id)
        )
        self.is_active = True
        logger.info("Started Nova Sonic bidirectional stream")
        
        # Send session start event
        session_start = json.dumps({
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {
                        "maxTokens": self.config.max_tokens,
                        "topP": self.config.top_p,
                        "temperature": self.config.temperature
                    }
                }
            }
        })
        await self._send_event(session_start)
        
        # Send prompt start with audio output configuration
        prompt_start = json.dumps({
            "event": {
                "promptStart": {
                    "promptName": self.prompt_name,
                    "textOutputConfiguration": {
                        "mediaType": "text/plain"
                    },
                    "audioOutputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": self.config.output_sample_rate,
                        "sampleSizeBits": self.config.sample_bits,
                        "channelCount": self.config.channels,
                        "voiceId": self.config.voice_id,
                        "encoding": "base64",
                        "audioType": "SPEECH"
                    }
                }
            }
        })
        await self._send_event(prompt_start)
        
        # Send system prompt if set
        if self.config.system_prompt:
            await self._send_system_prompt()
            
        # Start processing responses
        self.response_task = asyncio.create_task(self._process_responses())
        logger.info("Nova Sonic session started, response processor running")
        
    async def _send_system_prompt(self):
        """Send the system prompt as text content."""
        # Content start for system prompt
        content_start = json.dumps({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": self.content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "SYSTEM",
                    "textInputConfiguration": {
                        "mediaType": "text/plain"
                    }
                }
            }
        })
        await self._send_event(content_start)
        
        # The actual text
        text_input = json.dumps({
            "event": {
                "textInput": {
                    "promptName": self.prompt_name,
                    "contentName": self.content_name,
                    "content": self.config.system_prompt
                }
            }
        })
        await self._send_event(text_input)
        
        # Content end
        content_end = json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": self.content_name
                }
            }
        })
        await self._send_event(content_end)
        logger.debug("System prompt sent")
        
    async def start_audio_input(self):
        """Start streaming audio input to Nova Sonic."""
        self.audio_content_name = str(uuid.uuid4())  # New content ID for each audio stream
        
        audio_content_start = json.dumps({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": self.config.input_sample_rate,
                        "sampleSizeBits": self.config.sample_bits,
                        "channelCount": self.config.channels,
                        "audioType": "SPEECH",
                        "encoding": "base64"
                    }
                }
            }
        })
        await self._send_event(audio_content_start)
        logger.debug("Audio input stream started")
        
    async def send_audio_chunk(self, audio_bytes: bytes):
        """Send an audio chunk to Nova Sonic for processing."""
        if not self.is_active:
            return
            
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        audio_event = json.dumps({
            "event": {
                "audioInput": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name,
                    "content": audio_b64
                }
            }
        })
        await self._send_event(audio_event)
        
    async def end_audio_input(self):
        """End the current audio input stream."""
        audio_content_end = json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name
                }
            }
        })
        await self._send_event(audio_content_end)
        logger.debug("Audio input stream ended")
        
    async def send_text_message(self, text: str, role: str = "USER"):
        """Send a text message (useful for testing without audio)."""
        text_content_name = str(uuid.uuid4())
        
        # Content start
        content_start = json.dumps({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": text_content_name,
                    "type": "TEXT",
                    "interactive": True,
                    "role": role,
                    "textInputConfiguration": {
                        "mediaType": "text/plain"
                    }
                }
            }
        })
        await self._send_event(content_start)
        
        # Text input
        text_input = json.dumps({
            "event": {
                "textInput": {
                    "promptName": self.prompt_name,
                    "contentName": text_content_name,
                    "content": text
                }
            }
        })
        await self._send_event(text_input)
        
        # Content end
        content_end = json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": text_content_name
                }
            }
        })
        await self._send_event(content_end)
        logger.debug(f"Text message sent: {text[:50]}...")
        
    async def end_session(self):
        """End the Nova Sonic session and clean up."""
        if not self.is_active:
            return
            
        self.is_active = False
        
        # Send prompt end
        prompt_end = json.dumps({
            "event": {
                "promptEnd": {
                    "promptName": self.prompt_name
                }
            }
        })
        await self._send_event(prompt_end)
        
        # Send session end
        session_end = json.dumps({
            "event": {
                "sessionEnd": {}
            }
        })
        await self._send_event(session_end)
        
        # Close the stream
        await self.stream.input_stream.close()
        
        # Cancel response task
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
            try:
                await self.response_task
            except asyncio.CancelledError:
                pass
                
        logger.info("Nova Sonic session ended")
        
    async def _process_responses(self):
        """Process responses from the bidirectional stream."""
        try:
            while self.is_active:
                output = await self.stream.await_output()
                result = await output[1].receive()
                
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode('utf-8')
                    json_data = json.loads(response_data)
                    
                    if 'event' in json_data:
                        await self._handle_event(json_data['event'])
                        
        except asyncio.CancelledError:
            logger.debug("Response processor cancelled")
        except Exception as e:
            logger.error(f"Error processing responses: {e}")
            
    async def _handle_event(self, event: Dict[str, Any]):
        """Handle a single event from Nova Sonic."""
        
        if 'contentStart' in event:
            content_start = event['contentStart']
            self.current_role = content_start.get('role')
            
            # Check for speculative vs final content
            if 'additionalModelFields' in content_start:
                additional = json.loads(content_start['additionalModelFields'])
                self.display_assistant_text = additional.get('generationStage') == 'SPECULATIVE'
            else:
                self.display_assistant_text = False
                
        elif 'textOutput' in event:
            text = event['textOutput']['content']
            
            if self.current_role == "USER":
                # User transcript (what was heard)
                logger.info(f"User: {text}")
                if self.on_transcript:
                    self.on_transcript("user", text)
                self._current_transcript = text
                    
            elif self.current_role == "ASSISTANT" and self.display_assistant_text:
                # Assistant response
                logger.info(f"Assistant: {text}")
                if self.on_transcript:
                    self.on_transcript("assistant", text)
                    
        elif 'audioOutput' in event:
            audio_content = event['audioOutput']['content']
            audio_bytes = base64.b64decode(audio_content)
            
            # Put in queue for playback
            await self.audio_queue.put(audio_bytes)
            
            # Callback
            if self.on_speech_output:
                self.on_speech_output(audio_bytes)
                
        elif 'contentEnd' in event:
            # Turn completed
            if self.current_role and self._current_transcript:
                turn = ConversationTurn(
                    role=self.current_role.lower(),
                    content=self._current_transcript,
                    timestamp=datetime.now(timezone.utc)
                )
                self.conversation_history.append(turn)
                if self.on_turn_complete:
                    self.on_turn_complete(turn)
                self._current_transcript = ""
                
    async def get_audio_output(self) -> Optional[bytes]:
        """Get the next audio chunk from the output queue."""
        try:
            return await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
            
    async def process_webrtc_audio(
        self,
        audio_stream: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[bytes, None]:
        """
        Process WebRTC audio stream through Nova Sonic.
        
        This is the main interface for the voice tester.
        Receives audio from Connect, sends to Nova Sonic, yields responses.
        """
        if not self.is_active:
            await self.start_session()
            
        await self.start_audio_input()
        
        try:
            async for chunk in audio_stream:
                # Send input to Nova Sonic
                await self.send_audio_chunk(chunk)
                
                # Yield any available output
                while not self.audio_queue.empty():
                    audio = await self.audio_queue.get()
                    yield audio
                    
                await asyncio.sleep(0.01)  # Small delay to prevent busy loop
                
        finally:
            await self.end_audio_input()
            
            # Drain remaining audio output
            while not self.audio_queue.empty():
                audio = await self.audio_queue.get()
                yield audio


# Convenience function for one-shot responses
async def generate_response(
    input_audio: bytes,
    system_prompt: str = "",
    config: NovaSonicConfig = None
) -> tuple[str, bytes]:
    """
    Generate a single response to input audio.
    
    Returns (transcript, audio_response)
    """
    client = NovaSonicVoiceClient(config)
    client.config.system_prompt = system_prompt
    
    transcript = ""
    response_audio = bytearray()
    
    def on_transcript(role, text):
        nonlocal transcript
        if role == "assistant":
            transcript = text
            
    def on_audio(audio):
        response_audio.extend(audio)
        
    client.on_transcript = on_transcript
    client.on_speech_output = on_audio
    
    try:
        await client.start_session()
        await client.start_audio_input()
        
        # Send all audio
        chunk_size = 1024
        for i in range(0, len(input_audio), chunk_size):
            chunk = input_audio[i:i+chunk_size]
            await client.send_audio_chunk(chunk)
            await asyncio.sleep(0.01)
            
        await client.end_audio_input()
        
        # Wait for response
        await asyncio.sleep(2.0)
        
    finally:
        await client.end_session()
        
    return transcript, bytes(response_audio)


if __name__ == "__main__":
    # Simple test
    async def test():
        config = NovaSonicConfig(region="us-east-1")
        client = NovaSonicVoiceClient(config)
        
        client.set_persona({
            "name": "Test Caller",
            "background": "Testing the system",
            "attributes": {"speaking_rate": "normal", "patience": "high"}
        })
        
        print("Starting Nova Sonic session...")
        await client.start_session()
        
        # Send a text message for testing
        await client.send_text_message("Hello, I'd like to check my account balance please.")
        
        # Wait for response
        print("Waiting for response...")
        await asyncio.sleep(5.0)
        
        # Get audio output
        audio_chunks = []
        while not client.audio_queue.empty():
            chunk = await client.get_audio_output()
            if chunk:
                audio_chunks.append(chunk)
                
        print(f"Received {len(audio_chunks)} audio chunks")
        
        await client.end_session()
        print("Session ended")
        
    asyncio.run(test())
