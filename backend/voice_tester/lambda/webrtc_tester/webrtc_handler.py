"""
WebRTC Tester Lambda Handler

Handles WebRTC-based voice testing for Amazon Connect.
This provides a direct, phone-number-free way to test Connect contact flows.
"""
import asyncio
import json
import logging
import os
import base64
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# Initialize AWS clients
connect = boto3.client('connect')
connect_participant = boto3.client('connectparticipant')
polly = boto3.client('polly')
bedrock = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
CONNECT_INSTANCE_ID = os.environ.get('CONNECT_INSTANCE_ID', '')
CONTACT_FLOW_ID = os.environ.get('CONTACT_FLOW_ID', '')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')
POLLY_VOICE_ID = os.environ.get('POLLY_VOICE_ID', 'Joanna')
POLLY_ENGINE = os.environ.get('POLLY_ENGINE', 'neural')
CALL_STATE_TABLE = os.environ.get('CALL_STATE_TABLE', 'VoiceTestCallState')
TEST_RESULTS_TABLE = os.environ.get('TEST_RESULTS_TABLE', 'VoiceTestResults')
RECORDINGS_BUCKET = os.environ.get('RECORDINGS_BUCKET', '')


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder for Decimal types from DynamoDB"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main Lambda handler for WebRTC voice testing.
    
    Supported operations:
    - start_test: Start a WebRTC voice test
    - check_status: Check test status
    - get_results: Get test results
    - send_message: Send a message in ongoing test
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    operation = event.get('operation', 'start_test')
    
    handlers = {
        'start_test': handle_start_test,
        'check_status': handle_check_status,
        'get_results': handle_get_results,
        'send_message': handle_send_message,
        'list_instances': handle_list_instances,
        'list_contact_flows': handle_list_contact_flows,
    }
    
    handler = handlers.get(operation)
    if not handler:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Unknown operation: {operation}'})
        }
    
    try:
        result = handler(event)
        return {
            'statusCode': 200,
            'body': json.dumps(result, cls=DecimalEncoder)
        }
    except Exception as e:
        logger.error(f"Error handling {operation}: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def handle_start_test(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start a WebRTC-based voice test to Amazon Connect.
    
    This initiates a chat contact that can be upgraded to voice,
    or uses the WebRTC APIs directly.
    """
    scenario = event.get('scenario', {})
    test_id = event.get('test_id', str(uuid.uuid4()))
    instance_id = event.get('instance_id') or CONNECT_INSTANCE_ID
    contact_flow_id = event.get('contact_flow_id') or CONTACT_FLOW_ID
    
    if not instance_id:
        return {'error': 'Connect instance ID required. Set CONNECT_INSTANCE_ID or pass instance_id'}
    
    if not contact_flow_id:
        return {'error': 'Contact flow ID required. Set CONTACT_FLOW_ID or pass contact_flow_id'}
    
    logger.info(f"Starting WebRTC test {test_id} to instance {instance_id}")
    
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Try WebRTC contact first, fall back to chat
    try:
        # Method 1: Direct WebRTC contact (preview/newer API)
        contact_response = start_webrtc_contact(instance_id, contact_flow_id, test_id)
    except Exception as e:
        logger.warning(f"WebRTC contact failed, trying chat: {e}")
        # Method 2: Start chat contact for message-based testing
        contact_response = start_chat_contact(instance_id, contact_flow_id, test_id)
    
    contact_id = contact_response.get('ContactId', '')
    participant_id = contact_response.get('ParticipantId', '')
    participant_token = contact_response.get('ParticipantToken', '')
    
    # Create participant connection
    connection_info = {}
    if participant_token:
        try:
            connection_info = connect_participant.create_participant_connection(
                Type=['WEBSOCKET', 'CONNECTION_CREDENTIALS'],
                ParticipantToken=participant_token,
                ConnectParticipant=True,
            )
        except Exception as e:
            logger.warning(f"Failed to create participant connection: {e}")
    
    # Store test state
    call_state_table = dynamodb.Table(CALL_STATE_TABLE)
    test_results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    call_state = {
        'call_id': contact_id or test_id,
        'test_id': test_id,
        'contact_id': contact_id,
        'participant_id': participant_id,
        'participant_token': participant_token,
        'websocket_url': connection_info.get('Websocket', {}).get('Url', ''),
        'connection_token': connection_info.get('ConnectionCredentials', {}).get('ConnectionToken', ''),
        'status': 'connected',
        'instance_id': instance_id,
        'contact_flow_id': contact_flow_id,
        'scenario': json.dumps(scenario),
        'conversation': json.dumps([]),
        'started_at': timestamp,
        'ttl': int(time.time()) + 3600,  # 1 hour TTL
    }
    
    call_state_table.put_item(Item=call_state)
    
    # Store test result placeholder
    test_result = {
        'test_id': test_id,
        'timestamp': timestamp,
        'scenario_name': scenario.get('name', 'unknown'),
        'status': 'in_progress',
        'contact_id': contact_id,
        'mode': 'webrtc',
    }
    test_results_table.put_item(Item=test_result)
    
    # Run conversation if scenario has steps
    if scenario.get('steps'):
        conversation = run_scenario_conversation(
            test_id=test_id,
            scenario=scenario,
            participant_token=participant_token,
            connection_token=connection_info.get('ConnectionCredentials', {}).get('ConnectionToken', ''),
        )
        
        # Update state with conversation
        call_state_table.update_item(
            Key={'call_id': contact_id or test_id},
            UpdateExpression='SET conversation = :conv, #s = :status',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':conv': json.dumps(conversation),
                ':status': 'completed',
            }
        )
        
        # Update test result
        test_results_table.update_item(
            Key={'test_id': test_id, 'timestamp': timestamp},
            UpdateExpression='SET #s = :status, conversation = :conv, ended_at = :ended',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': 'completed',
                ':conv': json.dumps(conversation),
                ':ended': datetime.now(timezone.utc).isoformat(),
            }
        )
    
    return {
        'test_id': test_id,
        'contact_id': contact_id,
        'participant_id': participant_id,
        'status': 'connected',
        'websocket_url': connection_info.get('Websocket', {}).get('Url', ''),
        'message': 'Test started successfully',
    }


def start_webrtc_contact(instance_id: str, contact_flow_id: str, test_id: str) -> Dict[str, Any]:
    """Start a WebRTC contact with Amazon Connect"""
    
    # Note: StartWebRTCContact is a preview feature
    # May require enablement in your Connect instance
    try:
        response = connect.start_web_rtc_contact(
            InstanceId=instance_id,
            ContactFlowId=contact_flow_id,
            ParticipantDetails={
                'DisplayName': f'AI Voice Tester ({test_id[:8]})'
            },
            AllowedCapabilities={
                'Customer': {
                    'Audio': 'SEND_AND_RECEIVE'
                },
                'Agent': {
                    'Audio': 'SEND_AND_RECEIVE'
                }
            },
            ClientToken=test_id,
        )
        return response
    except connect.exceptions.ClientError as e:
        # If WebRTC not available, raise to trigger fallback
        raise


def start_chat_contact(instance_id: str, contact_flow_id: str, test_id: str) -> Dict[str, Any]:
    """
    Start a chat contact with Amazon Connect.
    
    Chat contacts support text messaging, which we can use for testing
    Lex bots that accept text input (most do).
    """
    response = connect.start_chat_contact(
        InstanceId=instance_id,
        ContactFlowId=contact_flow_id,
        ParticipantDetails={
            'DisplayName': f'AI Voice Tester ({test_id[:8]})'
        },
        InitialMessage={
            'ContentType': 'text/plain',
            'Content': 'Hello'  # Initial greeting
        },
        ClientToken=test_id,
    )
    return response


def run_scenario_conversation(
    test_id: str,
    scenario: Dict[str, Any],
    participant_token: str,
    connection_token: str,
) -> List[Dict]:
    """
    Run through scenario steps using chat messaging.
    
    This allows testing the conversation flow without actual voice,
    which is useful for validating Lex bot behavior.
    """
    conversation = []
    steps = scenario.get('steps', [])
    persona = scenario.get('persona', {})
    
    for step_index, step in enumerate(steps):
        step_id = step.get('id', f'step_{step_index}')
        action = step.get('action', 'listen')
        
        logger.info(f"Executing step {step_id}: {action}")
        
        try:
            if action == 'listen':
                # In chat mode, we wait for and receive system messages
                transcript = get_chat_message(connection_token, timeout_seconds=15)
                if transcript:
                    conversation.append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'speaker': 'system',
                        'text': transcript,
                        'step_id': step_id,
                    })
                    
            elif action == 'speak':
                content = step.get('content', {})
                text = get_speak_content(content, persona, conversation, scenario)
                
                # Send message via chat
                send_chat_message(connection_token, text)
                
                conversation.append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'speaker': 'caller',
                    'text': text,
                    'step_id': step_id,
                })
                
            elif action == 'wait':
                duration_ms = step.get('duration_ms', 1000)
                time.sleep(duration_ms / 1000)
                
            elif action == 'hangup':
                disconnect_participant(connection_token)
                break
                
        except Exception as e:
            logger.error(f"Error in step {step_id}: {e}")
            conversation.append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'speaker': 'error',
                'text': str(e),
                'step_id': step_id,
            })
    
    return conversation


def get_speak_content(
    content: Dict,
    persona: Dict,
    conversation: List[Dict],
    scenario: Dict,
) -> str:
    """Determine what text to send"""
    
    content_type = content.get('type', 'literal')
    
    if content_type == 'literal':
        return content.get('text', 'Yes')
        
    elif content_type == 'random_choice':
        import random
        choices = content.get('choices', ['Yes'])
        return random.choice(choices)
        
    elif content_type == 'ai_generated':
        intent = content.get('intent', 'Respond naturally')
        return generate_ai_response(intent, persona, conversation, scenario)
    
    return 'Yes'


def generate_ai_response(
    intent: str,
    persona: Dict,
    conversation: List[Dict],
    scenario: Dict,
) -> str:
    """Generate AI response using Bedrock"""
    
    persona_name = persona.get('name', 'Standard Caller')
    background = persona.get('background', '')
    
    prompt = f"""You are playing the role of a caller in a customer service conversation test.

PERSONA: {persona_name}
BACKGROUND: {background}

CONVERSATION SO FAR:
"""
    for turn in conversation[-10:]:
        speaker = turn.get('speaker', 'unknown')
        text = turn.get('text', '')
        if speaker in ['system', 'bot']:
            prompt += f"SYSTEM: {text}\n"
        elif speaker in ['caller', 'ai']:
            prompt += f"YOU: {text}\n"
    
    prompt += f"""
YOUR INTENT: {intent}

Rules:
1. Respond naturally as if on a phone call
2. Keep response brief (1-2 sentences)
3. Only output the words you would say - no descriptions
4. Stay in character

RESPOND:"""
    
    try:
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "temperature": 0.7,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        
        result = json.loads(response['body'].read())
        text = result['content'][0]['text'].strip()
        
        # Clean up response
        text = text.strip('"')
        for prefix in ['Response:', 'YOU:', 'Caller:']:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        
        return text
        
    except Exception as e:
        logger.error(f"Error generating AI response: {e}")
        return "Yes"


def get_chat_message(connection_token: str, timeout_seconds: int = 15) -> str:
    """Get messages from chat using the connection token"""
    
    if not connection_token:
        return ""
    
    try:
        # Get transcript to see messages
        response = connect_participant.get_transcript(
            ConnectionToken=connection_token,
            MaxResults=10,
            SortOrder='ASCENDING',
        )
        
        # Find last system/agent message
        messages = response.get('Transcript', [])
        for item in reversed(messages):
            participant_role = item.get('ParticipantRole', '')
            if participant_role in ['SYSTEM', 'AGENT', 'BOT']:
                return item.get('Content', '')
        
        return ""
        
    except Exception as e:
        logger.warning(f"Error getting chat message: {e}")
        return ""


def send_chat_message(connection_token: str, text: str):
    """Send a message via chat"""
    
    if not connection_token:
        return
    
    try:
        connect_participant.send_message(
            ConnectionToken=connection_token,
            ContentType='text/plain',
            Content=text,
        )
    except Exception as e:
        logger.error(f"Error sending chat message: {e}")


def disconnect_participant(connection_token: str):
    """Disconnect from the chat"""
    
    if not connection_token:
        return
    
    try:
        connect_participant.disconnect_participant(
            ConnectionToken=connection_token,
        )
    except Exception as e:
        logger.warning(f"Error disconnecting: {e}")


def handle_check_status(event: Dict[str, Any]) -> Dict[str, Any]:
    """Check status of a test"""
    
    test_id = event.get('test_id', '')
    
    if not test_id:
        return {'error': 'test_id required'}
    
    call_state_table = dynamodb.Table(CALL_STATE_TABLE)
    
    # Check call state table
    response = call_state_table.query(
        IndexName='TestIdIndex' if 'TestIdIndex' in str(call_state_table.global_secondary_indexes or []) else None,
        KeyConditionExpression=Key('call_id').eq(test_id),
    ) if False else call_state_table.scan(
        FilterExpression='test_id = :tid',
        ExpressionAttributeValues={':tid': test_id}
    )
    
    items = response.get('Items', [])
    
    if not items:
        return {'test_id': test_id, 'status': 'not_found'}
    
    item = items[0]
    return {
        'test_id': test_id,
        'contact_id': item.get('contact_id', ''),
        'status': item.get('status', 'unknown'),
        'started_at': item.get('started_at', ''),
        'ended_at': item.get('ended_at', ''),
    }


def handle_get_results(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get results of a completed test"""
    
    test_id = event.get('test_id', '')
    
    if not test_id:
        return {'error': 'test_id required'}
    
    test_results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    response = test_results_table.query(
        KeyConditionExpression=Key('test_id').eq(test_id),
        ScanIndexForward=False,
        Limit=1,
    )
    
    items = response.get('Items', [])
    
    if not items:
        return {'test_id': test_id, 'error': 'not_found'}
    
    item = items[0]
    
    # Parse conversation
    conversation = []
    if item.get('conversation'):
        try:
            conversation = json.loads(item['conversation'])
        except:
            pass
    
    return {
        'test_id': test_id,
        'status': item.get('status', 'unknown'),
        'scenario_name': item.get('scenario_name', ''),
        'mode': item.get('mode', 'webrtc'),
        'started_at': item.get('timestamp', ''),
        'ended_at': item.get('ended_at', ''),
        'conversation': conversation,
    }


def handle_send_message(event: Dict[str, Any]) -> Dict[str, Any]:
    """Send a message in an ongoing test"""
    
    test_id = event.get('test_id', '')
    message = event.get('message', '')
    
    if not test_id or not message:
        return {'error': 'test_id and message required'}
    
    # Get connection token from state
    call_state_table = dynamodb.Table(CALL_STATE_TABLE)
    
    response = call_state_table.scan(
        FilterExpression='test_id = :tid',
        ExpressionAttributeValues={':tid': test_id}
    )
    
    items = response.get('Items', [])
    
    if not items:
        return {'error': 'test not found'}
    
    connection_token = items[0].get('connection_token', '')
    
    if not connection_token:
        return {'error': 'no connection token available'}
    
    send_chat_message(connection_token, message)
    
    return {'status': 'sent', 'message': message}


def handle_list_instances(event: Dict[str, Any]) -> Dict[str, Any]:
    """List available Connect instances"""
    
    try:
        response = connect.list_instances()
        
        instances = []
        for instance in response.get('InstanceSummaryList', []):
            instances.append({
                'id': instance.get('Id', ''),
                'arn': instance.get('Arn', ''),
                'alias': instance.get('InstanceAlias', ''),
                'status': instance.get('InstanceStatus', ''),
            })
        
        return {'instances': instances}
        
    except Exception as e:
        return {'error': str(e)}


def handle_list_contact_flows(event: Dict[str, Any]) -> Dict[str, Any]:
    """List contact flows for an instance"""
    
    instance_id = event.get('instance_id') or CONNECT_INSTANCE_ID
    
    if not instance_id:
        return {'error': 'instance_id required'}
    
    try:
        response = connect.list_contact_flows(
            InstanceId=instance_id,
            MaxResults=100,
        )
        
        flows = []
        for flow in response.get('ContactFlowSummaryList', []):
            flows.append({
                'id': flow.get('Id', ''),
                'arn': flow.get('Arn', ''),
                'name': flow.get('Name', ''),
                'type': flow.get('ContactFlowType', ''),
            })
        
        return {'contact_flows': flows}
        
    except Exception as e:
        return {'error': str(e)}
