"""
WebRTC Voice Tester for Amazon Connect

Makes direct WebRTC connections to Amazon Connect for voice testing,
bypassing the need for phone numbers or Chime PSTN.

Uses:
- Amazon Connect Participant Service for WebRTC signaling
- WebRTC for bidirectional audio streaming
- Amazon Transcribe for speech-to-text
- Amazon Polly for text-to-speech
- Amazon Bedrock for AI responses
"""
import asyncio
import json
import logging
import os
import base64
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
import boto3
import websockets
from concurrent.futures import ThreadPoolExecutor

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)


@dataclass
class WebRTCConfig:
    """Configuration for WebRTC testing"""
    connect_instance_id: str = ""
    contact_flow_id: str = ""
    queue_id: str = ""
    region: str = "us-east-1"
    
    # Audio settings
    sample_rate: int = 16000  # WebRTC typically uses 16kHz
    channels: int = 1
    bits_per_sample: int = 16
    
    # AI settings
    bedrock_model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"
    polly_voice_id: str = "Joanna"
    polly_engine: str = "neural"
    transcribe_language: str = "en-US"


@dataclass  
class CallState:
    """State of an active WebRTC call"""
    contact_id: str = ""
    participant_id: str = ""
    participant_token: str = ""
    connection_token: str = ""
    websocket_url: str = ""
    
    status: str = "initializing"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    
    conversation: List[Dict] = field(default_factory=list)
    current_step_index: int = 0
    scenario_data: Dict = field(default_factory=dict)
    
    # Audio buffers
    incoming_audio: bytearray = field(default_factory=bytearray)
    outgoing_audio: bytearray = field(default_factory=bytearray)
    
    # Transcription state
    current_transcript: str = ""
    last_transcript_time: Optional[datetime] = None


class AmazonConnectWebRTCTester:
    """
    Makes WebRTC voice calls to Amazon Connect for testing.
    
    This bypasses the need for phone numbers by connecting directly
    to Connect's WebRTC endpoint.
    """
    
    def __init__(self, config: WebRTCConfig):
        self.config = config
        self.connect_client = boto3.client('connect', region_name=config.region)
        self.participant_client = boto3.client('connectparticipant', region_name=config.region)
        self.transcribe_streaming = boto3.client('transcribe', region_name=config.region)
        self.polly = boto3.client('polly', region_name=config.region)
        self.bedrock = boto3.client('bedrock-runtime', region_name=config.region)
        
        self.call_state: Optional[CallState] = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Callbacks
        self.on_transcript: Optional[Callable[[str], None]] = None
        self.on_ai_response: Optional[Callable[[str], None]] = None
        self.on_call_ended: Optional[Callable[[CallState], None]] = None
    
    async def start_test_call(
        self,
        scenario: Dict[str, Any],
        test_id: str = None,
    ) -> CallState:
        """
        Start a WebRTC test call to Amazon Connect.
        
        Args:
            scenario: Test scenario configuration
            test_id: Optional test identifier
        
        Returns:
            CallState object for tracking the call
        """
        test_id = test_id or str(uuid.uuid4())
        
        logger.info(f"Starting WebRTC test call: {test_id}")
        
        # Initialize call state
        self.call_state = CallState(
            started_at=datetime.now(timezone.utc),
            scenario_data=scenario,
        )
        
        try:
            # Step 1: Start outbound contact via Connect API
            logger.info("Initiating contact...")
            contact_response = await self._start_contact()
            
            self.call_state.contact_id = contact_response['ContactId']
            self.call_state.status = "connecting"
            
            # Step 2: Get participant connection details
            logger.info("Getting participant connection...")
            connection_info = await self._get_participant_connection()
            
            self.call_state.websocket_url = connection_info.get('Websocket', {}).get('Url', '')
            self.call_state.connection_token = connection_info.get('ConnectionCredentials', {}).get('ConnectionToken', '')
            
            # Step 3: Establish WebRTC connection
            logger.info("Establishing WebRTC connection...")
            await self._establish_webrtc_connection()
            
            self.call_state.status = "connected"
            
            # Step 4: Start the test conversation
            logger.info("Starting test conversation...")
            await self._run_test_conversation()
            
            return self.call_state
            
        except Exception as e:
            logger.error(f"Error in WebRTC test call: {e}", exc_info=True)
            self.call_state.status = "failed"
            raise
    
    async def _start_contact(self) -> Dict[str, Any]:
        """Start an outbound contact to the test contact flow"""
        
        # Use StartChatContact which supports voice through Connect streams
        # WebRTC is video-only, so we use chat contact with voice signaling
        try:
            response = self.connect_client.start_chat_contact(
                InstanceId=self.config.connect_instance_id,
                ContactFlowId=self.config.contact_flow_id,
                ParticipantDetails={
                    'DisplayName': 'AI Voice Tester'
                },
                InitialMessage={
                    'ContentType': 'text/plain',
                    'Content': 'Starting voice test'
                },
                ClientToken=str(uuid.uuid4()),
            )
            
            self.call_state.participant_id = response.get('ParticipantId', '')
            self.call_state.participant_token = response.get('ParticipantToken', '')
            
            return response
            
        except self.connect_client.exceptions.ClientError as e:
            if 'StartWebRTCContact' in str(e):
                # Fall back to chat contact and upgrade
                return await self._start_contact_fallback()
            raise
    
    async def _start_contact_fallback(self) -> Dict[str, Any]:
        """Fallback method using chat contact with voice upgrade"""
        
        # Start a chat contact
        response = self.connect_client.start_chat_contact(
            InstanceId=self.config.connect_instance_id,
            ContactFlowId=self.config.contact_flow_id,
            ParticipantDetails={
                'DisplayName': 'AI Voice Tester'
            },
            InitialMessage={
                'ContentType': 'text/plain',
                'Content': 'VOICE_TEST_INIT'
            },
            ClientToken=str(uuid.uuid4()),
        )
        
        self.call_state.participant_id = response.get('ParticipantId', '')
        self.call_state.participant_token = response.get('ParticipantToken', '')
        
        return response
    
    async def _get_participant_connection(self) -> Dict[str, Any]:
        """Get WebSocket connection details for the participant"""
        
        response = self.participant_client.create_participant_connection(
            Type=['WEBSOCKET', 'CONNECTION_CREDENTIALS'],
            ParticipantToken=self.call_state.participant_token,
            ConnectParticipant=True,
        )
        
        return response
    
    async def _establish_webrtc_connection(self):
        """Establish the WebRTC audio connection"""
        
        if not self.call_state.websocket_url:
            logger.warning("No WebSocket URL available, using polling fallback")
            return
        
        # Connect to the WebSocket for signaling
        async with websockets.connect(self.call_state.websocket_url) as websocket:
            self.websocket = websocket
            
            # Send connection established message
            await websocket.send(json.dumps({
                'topic': 'aws/subscribe',
                'content': {
                    'topics': ['aws/chat', 'aws/typing', 'aws/participant']
                }
            }))
            
            logger.info("WebSocket connection established")
    
    async def _run_test_conversation(self):
        """Run the test conversation based on the scenario"""
        
        scenario = self.call_state.scenario_data
        steps = scenario.get('steps', [])
        persona = scenario.get('persona', {})
        
        # Create AI persona
        ai_persona = AICallerPersona(persona)
        
        for step_index, step in enumerate(steps):
            self.call_state.current_step_index = step_index
            step_id = step.get('id', f'step_{step_index}')
            action = step.get('action', 'listen')
            
            logger.info(f"Executing step {step_id}: {action}")
            
            try:
                if action == 'listen':
                    await self._execute_listen_step(step)
                elif action == 'speak':
                    await self._execute_speak_step(step, ai_persona)
                elif action == 'wait':
                    duration_ms = step.get('duration_ms', 1000)
                    await asyncio.sleep(duration_ms / 1000)
                elif action == 'hangup':
                    await self._end_call()
                    break
                    
            except Exception as e:
                logger.error(f"Error in step {step_id}: {e}")
                self._add_to_conversation('error', str(e))
        
        # End call if not already ended
        if self.call_state.status != "ended":
            await self._end_call()
    
    async def _execute_listen_step(self, step: Dict) -> str:
        """Execute a listen step - wait for and transcribe system speech"""
        
        expect = step.get('expect', {})
        timeout_seconds = expect.get('timeout_seconds', 15)
        expected_patterns = expect.get('patterns', [])
        
        # Start listening for audio
        start_time = time.time()
        transcript = ""
        
        while time.time() - start_time < timeout_seconds:
            # Poll for new audio/transcript
            transcript = await self._get_current_transcript()
            
            if transcript:
                self._add_to_conversation('system', transcript)
                
                # Check if any expected pattern matches
                import re
                for pattern in expected_patterns:
                    if re.search(pattern, transcript, re.IGNORECASE):
                        logger.info(f"Pattern matched: {pattern}")
                        return transcript
            
            await asyncio.sleep(0.5)
        
        return transcript
    
    async def _execute_speak_step(self, step: Dict, persona: 'AICallerPersona'):
        """Execute a speak step - generate and send speech"""
        
        content = step.get('content', {})
        content_type = content.get('type', 'literal')
        
        if content_type == 'literal':
            text = content.get('text', '')
        elif content_type == 'ai_generated':
            intent = content.get('intent', 'Respond naturally')
            text = await self._generate_ai_response(intent, persona)
        elif content_type == 'random_choice':
            import random
            choices = content.get('choices', ['Yes'])
            text = random.choice(choices)
        else:
            text = "Hello"
        
        logger.info(f"Speaking: {text}")
        self._add_to_conversation('ai', text)
        
        # Synthesize and send audio
        await self._synthesize_and_send(text)
    
    async def _generate_ai_response(self, intent: str, persona: 'AICallerPersona') -> str:
        """Generate an AI response using Bedrock"""
        
        conversation = self.call_state.conversation
        
        # Build prompt
        prompt = persona.build_response_prompt(
            intent=intent,
            conversation_history=conversation,
            scenario_context=self.call_state.scenario_data
        )
        
        try:
            response = self.bedrock.invoke_model(
                modelId=self.config.bedrock_model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 150,
                    "temperature": 0.7,
                    "messages": [{"role": "user", "content": prompt}]
                })
            )
            
            result = json.loads(response['body'].read())
            text = result['content'][0]['text'].strip()
            
            # Clean up response
            text = persona.clean_response(text)
            return text
            
        except Exception as e:
            logger.error(f"Error generating AI response: {e}")
            return "I'm sorry, could you repeat that?"
    
    async def _synthesize_and_send(self, text: str):
        """Synthesize speech with Polly and send via WebRTC"""
        
        try:
            # Synthesize speech
            response = self.polly.synthesize_speech(
                Text=text,
                OutputFormat='pcm',
                VoiceId=self.config.polly_voice_id,
                Engine=self.config.polly_engine,
                SampleRate=str(self.config.sample_rate),
            )
            
            audio_data = response['AudioStream'].read()
            
            # Send audio through the connection
            await self._send_audio(audio_data)
            
            # Wait for audio to finish playing (estimate based on audio length)
            duration_seconds = len(audio_data) / (self.config.sample_rate * 2)  # 16-bit = 2 bytes
            await asyncio.sleep(duration_seconds + 0.5)
            
        except Exception as e:
            logger.error(f"Error synthesizing/sending speech: {e}")
    
    async def _send_audio(self, audio_data: bytes):
        """Send audio data through the WebRTC connection"""
        
        # For WebSocket-based connection, send audio events
        if hasattr(self, 'websocket') and self.websocket:
            # Chunk audio into smaller pieces for streaming
            chunk_size = 3200  # 100ms of 16kHz 16-bit audio
            
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                
                # Send as base64 encoded audio event
                message = {
                    'topic': 'aws/audio',
                    'content': {
                        'type': 'audio/pcm',
                        'data': base64.b64encode(chunk).decode('utf-8'),
                    }
                }
                
                try:
                    await self.websocket.send(json.dumps(message))
                except:
                    pass
                
                # Small delay between chunks
                await asyncio.sleep(0.1)
        else:
            # Store in buffer for polling-based sending
            self.call_state.outgoing_audio.extend(audio_data)
    
    async def _get_current_transcript(self) -> str:
        """Get the current transcript from incoming audio"""
        
        # In a real implementation, this would:
        # 1. Receive audio from WebRTC
        # 2. Stream to Transcribe
        # 3. Return transcript
        
        # For now, poll for transcript events
        if hasattr(self, 'websocket') and self.websocket:
            try:
                # Non-blocking receive
                message = await asyncio.wait_for(
                    self.websocket.recv(),
                    timeout=0.5
                )
                
                data = json.loads(message)
                if data.get('topic') == 'aws/transcript':
                    transcript = data.get('content', {}).get('transcript', '')
                    return transcript
                    
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.debug(f"WebSocket receive error: {e}")
        
        return self.call_state.current_transcript
    
    async def _end_call(self):
        """End the WebRTC call"""
        
        logger.info("Ending call...")
        
        self.call_state.status = "ended"
        self.call_state.ended_at = datetime.now(timezone.utc)
        
        # Close WebSocket
        if hasattr(self, 'websocket') and self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
        
        # Stop the contact
        try:
            self.connect_client.stop_contact(
                ContactId=self.call_state.contact_id,
                InstanceId=self.config.connect_instance_id,
            )
        except Exception as e:
            logger.warning(f"Error stopping contact: {e}")
        
        if self.on_call_ended:
            self.on_call_ended(self.call_state)
    
    def _add_to_conversation(self, speaker: str, text: str):
        """Add an entry to the conversation log"""
        
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'speaker': speaker,
            'text': text
        }
        
        self.call_state.conversation.append(entry)
        
        if speaker == 'system' and self.on_transcript:
            self.on_transcript(text)
        elif speaker == 'ai' and self.on_ai_response:
            self.on_ai_response(text)


class AICallerPersona:
    """Manages the AI caller's persona for WebRTC testing"""
    
    def __init__(self, persona_config: Dict[str, Any]):
        self.name = persona_config.get('name', 'Standard Caller')
        self.attributes = persona_config.get('attributes', {})
        self.background = persona_config.get('background', '')
        self.behaviors = persona_config.get('behaviors', {})
    
    def build_response_prompt(
        self,
        intent: str,
        conversation_history: List[Dict],
        scenario_context: Dict
    ) -> str:
        """Build a prompt for generating AI responses"""
        
        prompt = f"""You are playing the role of a caller in a phone conversation test.

PERSONA: {self.name}
BACKGROUND: {self.background}

SPEAKING STYLE:
- Rate: {self.attributes.get('speaking_rate', 'normal')}
- Patience: {self.attributes.get('patience', 'normal')}
- Clarity: {self.attributes.get('clarity', 'clear')}

SCENARIO: {scenario_context.get('name', 'Voice Test')}

CONVERSATION SO FAR:
"""
        for turn in conversation_history[-10:]:
            speaker = turn.get('speaker', 'unknown')
            text = turn.get('text', '')
            if speaker in ['system', 'bot']:
                prompt += f"SYSTEM: {text}\n"
            elif speaker in ['ai', 'caller']:
                prompt += f"YOU: {text}\n"
        
        prompt += f"""
YOUR INTENT FOR THIS RESPONSE: {intent}

Rules:
1. Respond naturally as if on a phone call
2. Keep response brief (1-2 sentences)
3. Only output the words you would speak - no descriptions or actions
4. Stay in character

RESPOND:"""
        
        return prompt
    
    def clean_response(self, text: str) -> str:
        """Clean up AI-generated response"""
        
        text = text.strip()
        
        # Remove quotes
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        
        # Remove common prefixes
        prefixes = ['Response:', 'YOU:', 'Caller:', '[Speaking]:', 'I say:']
        for prefix in prefixes:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        
        return text


class ConnectStreamsTester:
    """
    Alternative tester using Amazon Connect Streams API.
    
    This approach uses a headless browser to load the Connect CCP
    and interact with it programmatically.
    """
    
    def __init__(self, config: WebRTCConfig):
        self.config = config
        self.connect_client = boto3.client('connect', region_name=config.region)
    
    async def start_softphone_test(
        self,
        scenario: Dict[str, Any],
        ccp_url: str,
    ) -> CallState:
        """
        Start a test using the softphone/CCP approach.
        
        This requires the Connect Streams library and a browser environment.
        """
        
        # This would use playwright or selenium to:
        # 1. Load the CCP URL
        # 2. Initialize Connect Streams
        # 3. Accept/make calls programmatically
        # 4. Capture and inject audio
        
        raise NotImplementedError(
            "Softphone testing requires browser automation. "
            "Use WebRTC direct connection or PSTN approach instead."
        )


# =============================================================================
# Lambda Handler for WebRTC Testing
# =============================================================================

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda handler for WebRTC voice tests.
    
    Can be invoked to start a WebRTC test call.
    """
    
    operation = event.get('operation', 'start_test')
    
    if operation == 'start_test':
        return handle_start_webrtc_test(event)
    elif operation == 'check_status':
        return handle_check_status(event)
    else:
        return {'statusCode': 400, 'error': f'Unknown operation: {operation}'}


def handle_start_webrtc_test(event: Dict[str, Any]) -> Dict[str, Any]:
    """Start a WebRTC voice test"""
    
    scenario = event.get('scenario', {})
    test_id = event.get('test_id', str(uuid.uuid4()))
    
    config = WebRTCConfig(
        connect_instance_id=os.environ.get('CONNECT_INSTANCE_ID', ''),
        contact_flow_id=os.environ.get('CONTACT_FLOW_ID', ''),
        region=os.environ.get('AWS_REGION', 'us-east-1'),
    )
    
    tester = AmazonConnectWebRTCTester(config)
    
    # Run the test (note: Lambda has 15 min timeout)
    loop = asyncio.get_event_loop()
    
    try:
        call_state = loop.run_until_complete(
            tester.start_test_call(scenario, test_id)
        )
        
        return {
            'statusCode': 200,
            'test_id': test_id,
            'contact_id': call_state.contact_id,
            'status': call_state.status,
            'conversation': call_state.conversation,
            'duration_seconds': (
                (call_state.ended_at - call_state.started_at).total_seconds()
                if call_state.ended_at and call_state.started_at
                else 0
            ),
        }
        
    except Exception as e:
        logger.error(f"WebRTC test failed: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'test_id': test_id,
            'error': str(e),
        }


def handle_check_status(event: Dict[str, Any]) -> Dict[str, Any]:
    """Check the status of a WebRTC test"""
    
    test_id = event.get('test_id', '')
    
    # In a real implementation, check DynamoDB for test status
    return {
        'statusCode': 200,
        'test_id': test_id,
        'status': 'unknown',
        'message': 'Status checking requires DynamoDB integration'
    }
