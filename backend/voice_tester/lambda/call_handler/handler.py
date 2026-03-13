"""
Call Handler Lambda

Handles Amazon Chime SDK SIP Media Application (PSMA) events.
This is the entry point for all voice calls made by the testing system.

Event Flow:
1. NEW_INBOUND_CALL / NEW_OUTBOUND_CALL - Call initiated
2. RINGING - Target phone ringing
3. CALL_ANSWERED - Call connected
4. ACTION_SUCCESSFUL / ACTION_FAILED - Action results
5. HANGUP - Call ended
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import boto3
from boto3.dynamodb.conditions import Key

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
lambda_client = boto3.client('lambda')

# Environment
CALL_STATE_TABLE = os.environ.get('CALL_STATE_TABLE', 'VoiceTestCallState')
TEST_RESULTS_TABLE = os.environ.get('TEST_RESULTS_TABLE', 'VoiceTestResults')
RECORDINGS_BUCKET = os.environ.get('RECORDINGS_BUCKET', '')
AUDIO_PROCESSOR_ARN = os.environ.get('AUDIO_PROCESSOR_ARN', '')


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main handler for Chime SDK SIP Media Application events.
    
    Returns PSMA actions to control the call flow.
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    # Extract event details
    invoke_event = event.get('InvocationEventType', '')
    call_details = event.get('CallDetails', {})
    transaction_id = call_details.get('TransactionId', '')
    
    participants = call_details.get('Participants', [])
    caller = next((p for p in participants if p.get('Direction') == 'Outbound'), {})
    callee = next((p for p in participants if p.get('Direction') == 'Inbound'), {})
    
    call_id = caller.get('CallId', transaction_id)
    
    logger.info(f"Event: {invoke_event}, CallId: {call_id}")
    
    try:
        if invoke_event == 'NEW_OUTBOUND_CALL':
            return handle_new_outbound_call(event, call_id, transaction_id)
        
        elif invoke_event == 'RINGING':
            return handle_ringing(event, call_id)
        
        elif invoke_event == 'CALL_ANSWERED':
            return handle_call_answered(event, call_id)
        
        elif invoke_event == 'ACTION_SUCCESSFUL':
            return handle_action_successful(event, call_id)
        
        elif invoke_event == 'ACTION_FAILED':
            return handle_action_failed(event, call_id)
        
        elif invoke_event == 'HANGUP':
            return handle_hangup(event, call_id)
        
        elif invoke_event == 'CALL_UPDATE_REQUESTED':
            return handle_call_update(event, call_id)
        
        else:
            logger.warning(f"Unhandled event type: {invoke_event}")
            return {"SchemaVersion": "1.0", "Actions": []}
    
    except Exception as e:
        logger.error(f"Error handling event: {str(e)}", exc_info=True)
        # Hang up on error
        return {
            "SchemaVersion": "1.0",
            "Actions": [{"Type": "Hangup", "Parameters": {"SipResponseCode": "500"}}]
        }


def handle_new_outbound_call(event: Dict, call_id: str, transaction_id: str) -> Dict:
    """Handle new outbound call - initialize call state"""
    logger.info(f"New outbound call: {call_id}")
    
    # Get test parameters from the call attributes
    call_details = event.get('CallDetails', {})
    sip_headers = call_details.get('SipHeaders', {})
    
    # Initialize call state in DynamoDB
    table = dynamodb.Table(CALL_STATE_TABLE)
    
    call_state = {
        'call_id': call_id,
        'transaction_id': transaction_id,
        'status': 'INITIATING',
        'test_id': sip_headers.get('X-Test-Id', str(uuid.uuid4())),
        'scenario_name': sip_headers.get('X-Scenario', 'unknown'),
        'started_at': datetime.now(timezone.utc).isoformat(),
        'conversation': [],
        'current_step_index': 0,
        'ttl': int(datetime.now(timezone.utc).timestamp()) + 3600,  # 1 hour TTL
    }
    
    table.put_item(Item=call_state)
    
    # Return empty actions - wait for RINGING/CALL_ANSWERED
    return {"SchemaVersion": "1.0", "Actions": []}


def handle_ringing(event: Dict, call_id: str) -> Dict:
    """Handle ringing event"""
    logger.info(f"Call ringing: {call_id}")
    
    update_call_state(call_id, {'status': 'RINGING'})
    
    # Just wait for answer
    return {"SchemaVersion": "1.0", "Actions": []}


def handle_call_answered(event: Dict, call_id: str) -> Dict:
    """
    Handle call answered - start the test conversation.
    
    This is where the magic happens:
    1. Start recording the call
    2. Start listening for speech (via Transcribe)
    3. Wait for the greeting from the system under test
    """
    logger.info(f"Call answered: {call_id}")
    
    update_call_state(call_id, {
        'status': 'CONNECTED',
        'answered_at': datetime.now(timezone.utc).isoformat()
    })
    
    # Get call state to determine first action
    call_state = get_call_state(call_id)
    
    actions = []
    
    # Start recording
    if RECORDINGS_BUCKET:
        actions.append({
            "Type": "StartCallRecording",
            "Parameters": {
                "Track": "BOTH",  # Record both sides
                "Destination": {
                    "Type": "S3",
                    "BucketName": RECORDINGS_BUCKET,
                    "Prefix": f"recordings/{call_state.get('test_id', call_id)}/",
                },
            }
        })
    
    # Start receiving audio (this triggers audio streaming that we'll process)
    # The audio will be processed by audio_processor Lambda
    actions.append({
        "Type": "ReceiveDigits",
        "Parameters": {
            "InputDigitsRegex": "^[0-9#*]{1,20}$",  # Accept DTMF if needed
            "InBetweenDigitsDurationInMilliseconds": 5000,
            "FlushDigitsDurationInMilliseconds": 10000,
        }
    })
    
    # Pause briefly to let the system greeting play
    actions.append({
        "Type": "Pause",
        "Parameters": {
            "DurationInMilliseconds": 2000
        }
    })
    
    return {
        "SchemaVersion": "1.0",
        "Actions": actions,
        "TransactionAttributes": {
            "testId": call_state.get('test_id', ''),
            "callId": call_id,
        }
    }


def handle_action_successful(event: Dict, call_id: str) -> Dict:
    """Handle successful action completion"""
    action_data = event.get('ActionData', {})
    action_type = action_data.get('Type', '')
    
    logger.info(f"Action successful: {action_type} for call {call_id}")
    
    call_state = get_call_state(call_id)
    if not call_state:
        logger.error(f"No call state found for {call_id}")
        return {"SchemaVersion": "1.0", "Actions": [{"Type": "Hangup"}]}
    
    # Handle based on action type
    if action_type == 'Pause':
        # After pause, typically we want to speak or listen
        return generate_next_action(call_id, call_state)
    
    elif action_type == 'Speak':
        # After speaking, listen for response
        return {
            "SchemaVersion": "1.0",
            "Actions": [
                {
                    "Type": "Pause",
                    "Parameters": {"DurationInMilliseconds": 500}
                }
            ]
        }
    
    elif action_type == 'PlayAudio':
        # After playing audio, continue with next step
        return generate_next_action(call_id, call_state)
    
    elif action_type == 'ReceiveDigits':
        received = action_data.get('ReceivedDigits', '')
        if received:
            add_to_conversation(call_id, 'dtmf_received', received)
        return generate_next_action(call_id, call_state)
    
    elif action_type == 'StartCallRecording':
        update_call_state(call_id, {'recording_started': True})
        return {"SchemaVersion": "1.0", "Actions": []}
    
    return {"SchemaVersion": "1.0", "Actions": []}


def handle_action_failed(event: Dict, call_id: str) -> Dict:
    """Handle failed action"""
    action_data = event.get('ActionData', {})
    action_type = action_data.get('Type', '')
    error = action_data.get('Error', 'Unknown error')
    
    logger.error(f"Action failed: {action_type} - {error} for call {call_id}")
    
    add_to_conversation(call_id, 'error', f"Action {action_type} failed: {error}")
    
    # Decide whether to retry or hang up
    if 'timeout' in error.lower():
        # Timeout might be expected - continue
        return generate_next_action(call_id, get_call_state(call_id))
    
    # For other errors, hang up
    return {
        "SchemaVersion": "1.0",
        "Actions": [{"Type": "Hangup", "Parameters": {"SipResponseCode": "500"}}]
    }


def handle_hangup(event: Dict, call_id: str) -> Dict:
    """Handle call hangup - finalize test results"""
    logger.info(f"Call hangup: {call_id}")
    
    call_state = get_call_state(call_id)
    if not call_state:
        return {"SchemaVersion": "1.0", "Actions": []}
    
    # Update final state
    update_call_state(call_id, {
        'status': 'COMPLETED',
        'ended_at': datetime.now(timezone.utc).isoformat()
    })
    
    # Save test results
    save_test_results(call_state)
    
    return {"SchemaVersion": "1.0", "Actions": []}


def handle_call_update(event: Dict, call_id: str) -> Dict:
    """
    Handle call update requests from external sources.
    
    This allows the AI responder to inject speech into the call.
    """
    logger.info(f"Call update requested: {call_id}")
    
    action_data = event.get('ActionData', {})
    requested_action = action_data.get('RequestedAction', '')
    
    if requested_action == 'Speak':
        text = action_data.get('Text', '')
        if text:
            return {
                "SchemaVersion": "1.0",
                "Actions": [
                    {
                        "Type": "Speak",
                        "Parameters": {
                            "Text": text,
                            "Engine": "neural",
                            "LanguageCode": "en-US",
                            "VoiceId": "Joanna",
                        }
                    }
                ]
            }
    
    return {"SchemaVersion": "1.0", "Actions": []}


def generate_next_action(call_id: str, call_state: Dict) -> Dict:
    """
    Generate the next action based on test scenario and conversation state.
    
    This is where we coordinate with the AI to determine what to say next.
    """
    # Invoke AI responder to get next utterance
    # For now, implement basic state machine
    
    current_step = call_state.get('current_step_index', 0)
    scenario = call_state.get('scenario_data', {})
    steps = scenario.get('steps', [])
    
    if current_step >= len(steps):
        # Test complete - hang up
        logger.info(f"Test complete for call {call_id}")
        update_call_state(call_id, {'status': 'TEST_COMPLETE'})
        return {
            "SchemaVersion": "1.0",
            "Actions": [
                {
                    "Type": "Pause",
                    "Parameters": {"DurationInMilliseconds": 1000}
                },
                {"Type": "Hangup", "Parameters": {"SipResponseCode": "200"}}
            ]
        }
    
    step = steps[current_step]
    action = step.get('action', 'listen')
    
    if action == 'speak':
        text = step.get('content', {}).get('text', 'Hello')
        add_to_conversation(call_id, 'ai_spoke', text)
        
        # Move to next step
        update_call_state(call_id, {'current_step_index': current_step + 1})
        
        return {
            "SchemaVersion": "1.0",
            "Actions": [
                {
                    "Type": "Speak",
                    "Parameters": {
                        "Text": text,
                        "Engine": "neural",
                        "LanguageCode": "en-US",
                        "VoiceId": "Joanna",
                    }
                }
            ]
        }
    
    elif action == 'listen':
        # Listen for response - use silence detection
        timeout_ms = step.get('expect', {}).get('timeout_seconds', 10) * 1000
        
        update_call_state(call_id, {'current_step_index': current_step + 1})
        
        return {
            "SchemaVersion": "1.0",
            "Actions": [
                {
                    "Type": "Pause",
                    "Parameters": {"DurationInMilliseconds": timeout_ms}
                }
            ]
        }
    
    # Default: pause and continue
    return {
        "SchemaVersion": "1.0",
        "Actions": [
            {
                "Type": "Pause",
                "Parameters": {"DurationInMilliseconds": 1000}
            }
        ]
    }


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


def update_call_state(call_id: str, updates: Dict) -> None:
    """Update call state in DynamoDB"""
    table = dynamodb.Table(CALL_STATE_TABLE)
    
    update_expr_parts = []
    expr_attr_values = {}
    expr_attr_names = {}
    
    for key, value in updates.items():
        safe_key = f"#{key}"
        expr_attr_names[safe_key] = key
        expr_attr_values[f":{key}"] = value
        update_expr_parts.append(f"{safe_key} = :{key}")
    
    if update_expr_parts:
        try:
            table.update_item(
                Key={'call_id': call_id},
                UpdateExpression="SET " + ", ".join(update_expr_parts),
                ExpressionAttributeNames=expr_attr_names,
                ExpressionAttributeValues=expr_attr_values
            )
        except Exception as e:
            logger.error(f"Error updating call state: {e}")


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


def save_test_results(call_state: Dict) -> None:
    """Save final test results to results table"""
    table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    test_result = {
        'test_id': call_state.get('test_id', call_state['call_id']),
        'timestamp': call_state.get('started_at', datetime.now(timezone.utc).isoformat()),
        'scenario_name': call_state.get('scenario_name', 'unknown'),
        'call_id': call_state['call_id'],
        'status': call_state.get('status', 'UNKNOWN'),
        'started_at': call_state.get('started_at'),
        'ended_at': call_state.get('ended_at'),
        'conversation': call_state.get('conversation', []),
        'recording_path': f"s3://{RECORDINGS_BUCKET}/recordings/{call_state.get('test_id', call_state['call_id'])}/",
    }
    
    try:
        table.put_item(Item=test_result)
        logger.info(f"Test results saved: {test_result['test_id']}")
    except Exception as e:
        logger.error(f"Error saving test results: {e}")
