"""
Audio Processor Lambda

Handles real-time audio processing for voice tests:
- Transcribes incoming audio using Amazon Transcribe Streaming
- Generates speech using Amazon Polly
- Coordinates with AI Responder for intelligent responses

This Lambda processes audio streams from the Chime SDK call.
"""
import json
import logging
import os
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Generator
import boto3
import struct

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# AWS clients
transcribe = boto3.client('transcribe')
polly = boto3.client('polly')
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

# Environment
RECORDINGS_BUCKET = os.environ.get('RECORDINGS_BUCKET', '')
CALL_STATE_TABLE = os.environ.get('CALL_STATE_TABLE', 'VoiceTestCallState')
AI_RESPONDER_ARN = os.environ.get('AI_RESPONDER_ARN', '')
POLLY_VOICE_ID = os.environ.get('POLLY_VOICE_ID', 'Joanna')
POLLY_ENGINE = os.environ.get('POLLY_ENGINE', 'neural')
TRANSCRIBE_LANGUAGE = os.environ.get('TRANSCRIBE_LANGUAGE', 'en-US')


class TranscriptionAccumulator:
    """Accumulates transcription results and detects complete utterances."""
    
    def __init__(self):
        self.partial_transcript = ""
        self.final_transcript = ""
        self.silence_start = None
        self.utterance_complete = False
        
    def add_result(self, result: Dict) -> Optional[str]:
        """
        Add a transcription result and return complete utterance if detected.
        
        Returns the complete utterance text when speech ends, otherwise None.
        """
        is_partial = result.get('IsPartial', True)
        transcript = result.get('Transcript', '')
        
        if is_partial:
            self.partial_transcript = transcript
            self.silence_start = None
            self.utterance_complete = False
        else:
            # Final result for this segment
            self.final_transcript += " " + transcript if self.final_transcript else transcript
            self.partial_transcript = ""
            
            # Check for utterance boundary (silence detection)
            self.silence_start = datetime.now(timezone.utc)
        
        return None
    
    def check_silence(self, silence_threshold_ms: int = 1500) -> Optional[str]:
        """
        Check if silence threshold exceeded, indicating utterance complete.
        
        Returns the complete utterance if silence detected, otherwise None.
        """
        if self.silence_start and self.final_transcript:
            elapsed = (datetime.now(timezone.utc) - self.silence_start).total_seconds() * 1000
            if elapsed >= silence_threshold_ms:
                utterance = self.final_transcript.strip()
                self.final_transcript = ""
                self.silence_start = None
                return utterance
        return None
    
    def get_current_text(self) -> str:
        """Get current accumulated text (final + partial)"""
        return (self.final_transcript + " " + self.partial_transcript).strip()


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main handler for audio processing.
    
    Supports multiple operation types:
    - transcribe_audio: Process audio and return transcription
    - synthesize_speech: Generate speech from text
    - process_stream: Handle streaming audio chunk
    """
    logger.info(f"Received event type: {event.get('operation', 'unknown')}")
    
    operation = event.get('operation', 'transcribe_audio')
    
    try:
        if operation == 'transcribe_audio':
            return handle_transcribe_audio(event)
        elif operation == 'synthesize_speech':
            return handle_synthesize_speech(event)
        elif operation == 'process_utterance':
            return handle_process_utterance(event)
        elif operation == 'get_ai_response':
            return handle_get_ai_response(event)
        else:
            return {
                'statusCode': 400,
                'error': f'Unknown operation: {operation}'
            }
    except Exception as e:
        logger.error(f"Error in audio processor: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e)
        }


def handle_transcribe_audio(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transcribe audio data using Amazon Transcribe.
    
    For batch transcription of recorded audio.
    """
    audio_data = event.get('audio_data', '')  # Base64 encoded
    audio_format = event.get('audio_format', 'pcm')
    sample_rate = event.get('sample_rate', 8000)
    call_id = event.get('call_id', '')
    
    if not audio_data:
        return {'statusCode': 400, 'error': 'audio_data is required'}
    
    # Decode audio
    audio_bytes = base64.b64decode(audio_data)
    
    # For short audio, use synchronous approach
    # Upload to S3 and start transcription job
    if RECORDINGS_BUCKET and call_id:
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        s3_key = f"temp_audio/{call_id}/{timestamp}.raw"
        
        s3.put_object(
            Bucket=RECORDINGS_BUCKET,
            Key=s3_key,
            Body=audio_bytes
        )
        
        # Start transcription job
        job_name = f"voice-test-{call_id}-{timestamp}"
        
        try:
            transcribe.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': f"s3://{RECORDINGS_BUCKET}/{s3_key}"},
                MediaFormat='wav' if audio_format == 'wav' else 'pcm',
                MediaSampleRateHertz=sample_rate,
                LanguageCode=TRANSCRIBE_LANGUAGE,
                OutputBucketName=RECORDINGS_BUCKET,
                OutputKey=f"transcripts/{call_id}/{timestamp}.json",
            )
            
            return {
                'statusCode': 202,
                'job_name': job_name,
                'message': 'Transcription job started'
            }
        except Exception as e:
            logger.error(f"Error starting transcription: {e}")
            return {'statusCode': 500, 'error': str(e)}
    
    return {'statusCode': 400, 'error': 'Missing bucket or call_id'}


def handle_synthesize_speech(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synthesize speech from text using Amazon Polly.
    
    Returns audio data that can be played back in the call.
    """
    text = event.get('text', '')
    voice_id = event.get('voice_id', POLLY_VOICE_ID)
    engine = event.get('engine', POLLY_ENGINE)
    output_format = event.get('output_format', 'pcm')
    sample_rate = event.get('sample_rate', '8000')
    
    if not text:
        return {'statusCode': 400, 'error': 'text is required'}
    
    try:
        # Use SSML for better control
        ssml_text = f"""<speak>
            <prosody rate="medium" pitch="medium">
                {text}
            </prosody>
        </speak>"""
        
        response = polly.synthesize_speech(
            Text=ssml_text,
            TextType='ssml',
            OutputFormat=output_format,
            VoiceId=voice_id,
            Engine=engine,
            SampleRate=sample_rate,
        )
        
        # Read audio stream
        audio_stream = response['AudioStream'].read()
        
        # Return base64 encoded audio
        return {
            'statusCode': 200,
            'audio_data': base64.b64encode(audio_stream).decode('utf-8'),
            'content_type': response['ContentType'],
            'characters_synthesized': len(text),
        }
        
    except Exception as e:
        logger.error(f"Error synthesizing speech: {e}")
        return {'statusCode': 500, 'error': str(e)}


def handle_process_utterance(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a complete utterance - transcribe, get AI response, synthesize reply.
    
    This is the main workflow for handling detected speech:
    1. Receive transcribed text (what the system said)
    2. Get AI response (what we should say)
    3. Synthesize speech for the response
    4. Return audio to play
    """
    call_id = event.get('call_id', '')
    transcribed_text = event.get('transcribed_text', '')
    
    if not call_id:
        return {'statusCode': 400, 'error': 'call_id is required'}
    
    logger.info(f"Processing utterance for {call_id}: {transcribed_text}")
    
    # Get call state
    call_state = get_call_state(call_id)
    if not call_state:
        return {'statusCode': 404, 'error': f'Call state not found for {call_id}'}
    
    # Add heard text to conversation
    if transcribed_text:
        add_to_conversation(call_id, 'system', transcribed_text)
    
    # Get AI response
    ai_response = invoke_ai_responder(call_id, transcribed_text)
    response_text = ai_response.get('response_text', '')
    
    if not response_text:
        return {
            'statusCode': 200,
            'action': 'listen',
            'message': 'No response needed'
        }
    
    # Synthesize speech
    speech_result = handle_synthesize_speech({
        'text': response_text,
        'voice_id': POLLY_VOICE_ID,
        'engine': POLLY_ENGINE,
    })
    
    if speech_result.get('statusCode') != 200:
        logger.error(f"Speech synthesis failed: {speech_result}")
        return {
            'statusCode': 200,
            'action': 'speak_text',
            'text': response_text,  # Fallback to text-based speech
            'message': 'Synthesis failed, using text fallback'
        }
    
    return {
        'statusCode': 200,
        'action': 'play_audio',
        'response_text': response_text,
        'audio_data': speech_result['audio_data'],
        'content_type': speech_result['content_type'],
    }


def handle_get_ai_response(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get AI response without synthesizing speech.
    
    Useful when the call handler will use Chime's built-in Speak action.
    """
    call_id = event.get('call_id', '')
    heard_text = event.get('heard_text', '')
    
    if not call_id:
        return {'statusCode': 400, 'error': 'call_id is required'}
    
    response = invoke_ai_responder(call_id, heard_text)
    
    return {
        'statusCode': 200,
        'response_text': response.get('response_text', ''),
        'step_completed': response.get('step_completed', ''),
    }


def invoke_ai_responder(call_id: str, heard_text: str) -> Dict[str, Any]:
    """Invoke the AI responder Lambda to get next response"""
    
    if not AI_RESPONDER_ARN:
        logger.warning("AI_RESPONDER_ARN not configured")
        return {'response_text': 'Yes', 'step_completed': 'fallback'}
    
    try:
        response = lambda_client.invoke(
            FunctionName=AI_RESPONDER_ARN,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'call_id': call_id,
                'heard_text': heard_text,
                'request_type': 'generate_response'
            })
        )
        
        result = json.loads(response['Payload'].read())
        return result
        
    except Exception as e:
        logger.error(f"Error invoking AI responder: {e}")
        return {'response_text': 'Could you repeat that?', 'step_completed': 'error'}


# =============================================================================
# Audio Processing Utilities
# =============================================================================

def convert_audio_format(
    audio_bytes: bytes,
    from_format: str,
    to_format: str,
    sample_rate: int = 8000
) -> bytes:
    """
    Convert audio between formats.
    
    Supports: pcm (16-bit signed), mulaw, alaw
    """
    if from_format == to_format:
        return audio_bytes
    
    # PCM is our intermediate format
    if from_format == 'mulaw':
        pcm_bytes = mulaw_to_pcm(audio_bytes)
    elif from_format == 'alaw':
        pcm_bytes = alaw_to_pcm(audio_bytes)
    else:
        pcm_bytes = audio_bytes
    
    # Convert from PCM to target
    if to_format == 'mulaw':
        return pcm_to_mulaw(pcm_bytes)
    elif to_format == 'alaw':
        return pcm_to_alaw(pcm_bytes)
    else:
        return pcm_bytes


def pcm_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert 16-bit PCM to µ-law"""
    # µ-law encoding table constants
    BIAS = 0x84
    CLIP = 32635
    
    output = bytearray()
    
    # Process 2 bytes at a time (16-bit samples)
    for i in range(0, len(pcm_bytes), 2):
        if i + 1 < len(pcm_bytes):
            sample = struct.unpack('<h', pcm_bytes[i:i+2])[0]
        else:
            break
        
        # Get the sign bit
        sign = (sample >> 8) & 0x80
        if sign:
            sample = -sample
        
        # Clip
        if sample > CLIP:
            sample = CLIP
        
        # Add bias
        sample += BIAS
        
        # Find the segment
        exponent = 7
        exp_mask = 0x4000
        while exponent > 0 and (sample & exp_mask) == 0:
            exponent -= 1
            exp_mask >>= 1
        
        # Build the µ-law byte
        mantissa = (sample >> (exponent + 3)) & 0x0F
        mulaw_byte = ~(sign | (exponent << 4) | mantissa)
        
        output.append(mulaw_byte & 0xFF)
    
    return bytes(output)


def mulaw_to_pcm(mulaw_bytes: bytes) -> bytes:
    """Convert µ-law to 16-bit PCM"""
    # µ-law to linear conversion table
    exp_lut = [0, 132, 396, 924, 1980, 4092, 8316, 16764]
    
    output = bytearray()
    
    for byte in mulaw_bytes:
        byte = ~byte & 0xFF
        
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        
        sample = exp_lut[exponent] + (mantissa << (exponent + 3))
        
        if sign:
            sample = -sample
        
        output.extend(struct.pack('<h', sample))
    
    return bytes(output)


def alaw_to_pcm(alaw_bytes: bytes) -> bytes:
    """Convert A-law to 16-bit PCM"""
    output = bytearray()
    
    for byte in alaw_bytes:
        byte ^= 0x55
        
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        
        if exponent == 0:
            sample = (mantissa << 4) + 8
        else:
            sample = ((mantissa << 4) + 0x108) << (exponent - 1)
        
        if sign:
            sample = -sample
        
        output.extend(struct.pack('<h', sample))
    
    return bytes(output)


def pcm_to_alaw(pcm_bytes: bytes) -> bytes:
    """Convert 16-bit PCM to A-law"""
    output = bytearray()
    
    for i in range(0, len(pcm_bytes), 2):
        if i + 1 < len(pcm_bytes):
            sample = struct.unpack('<h', pcm_bytes[i:i+2])[0]
        else:
            break
        
        # Get sign
        sign = 0 if sample >= 0 else 0x80
        if sample < 0:
            sample = -sample
        
        # Clip
        if sample > 32767:
            sample = 32767
        
        # Find segment
        if sample < 256:
            exponent = 0
            mantissa = sample >> 4
        else:
            exponent = 1
            temp = sample >> 5
            while temp > 15:
                temp >>= 1
                exponent += 1
            mantissa = temp
        
        alaw_byte = sign | (exponent << 4) | mantissa
        alaw_byte ^= 0x55
        
        output.append(alaw_byte)
    
    return bytes(output)


# =============================================================================
# Helper Functions
# =============================================================================

def get_call_state(call_id: str) -> Optional[Dict]:
    """Get call state from DynamoDB"""
    table = dynamodb.Table(CALL_STATE_TABLE)
    try:
        response = table.get_item(Key={'call_id': call_id})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting call state: {e}")
        return None


def add_to_conversation(call_id: str, speaker: str, text: str) -> None:
    """Add entry to conversation log"""
    table = dynamodb.Table(CALL_STATE_TABLE)
    
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'speaker': speaker,
        'text': text
    }
    
    try:
        table.update_item(
            Key={'call_id': call_id},
            UpdateExpression="SET conversation = list_append(if_not_exists(conversation, :empty), :entry)",
            ExpressionAttributeValues={
                ':entry': [entry],
                ':empty': []
            }
        )
    except Exception as e:
        logger.error(f"Error adding to conversation: {e}")
