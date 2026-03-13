"""
Test Runner Lambda

Orchestrates voice test execution:
- Loads test scenarios
- Initiates calls via Chime SDK
- Monitors test progress
- Generates test results

Can be invoked directly or via the CLI.
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
chime = boto3.client('chime-sdk-voice')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
lambda_client = boto3.client('lambda')

# Environment
CALL_STATE_TABLE = os.environ.get('CALL_STATE_TABLE', 'VoiceTestCallState')
TEST_RESULTS_TABLE = os.environ.get('TEST_RESULTS_TABLE', 'VoiceTestResults')
RECORDINGS_BUCKET = os.environ.get('RECORDINGS_BUCKET', '')
SIP_MEDIA_APP_ID = os.environ.get('SIP_MEDIA_APP_ID', '')
CHIME_PHONE_NUMBER = os.environ.get('CHIME_PHONE_NUMBER', '')


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main handler for test execution.
    
    Operations:
    - start_test: Start a new voice test
    - check_status: Check test status
    - get_results: Get test results
    - list_tests: List recent tests
    - cancel_test: Cancel an in-progress test
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    operation = event.get('operation', 'start_test')
    
    try:
        if operation == 'start_test':
            return handle_start_test(event)
        elif operation == 'check_status':
            return handle_check_status(event)
        elif operation == 'get_results':
            return handle_get_results(event)
        elif operation == 'list_tests':
            return handle_list_tests(event)
        elif operation == 'cancel_test':
            return handle_cancel_test(event)
        elif operation == 'provision_number':
            return handle_provision_number(event)
        else:
            return {
                'statusCode': 400,
                'error': f'Unknown operation: {operation}'
            }
    except Exception as e:
        logger.error(f"Error in test runner: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e)
        }


def handle_start_test(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start a new voice test.
    
    Expected event:
    {
        "operation": "start_test",
        "scenario": { ... scenario definition ... },
        "target_number": "+15551234567",  # Override from scenario
        "test_id": "optional-custom-id"
    }
    """
    scenario = event.get('scenario', {})
    target_number = event.get('target_number') or scenario.get('target', {}).get('phone_number')
    test_id = event.get('test_id', str(uuid.uuid4()))
    
    if not scenario:
        return {'statusCode': 400, 'error': 'scenario is required'}
    
    if not target_number:
        return {'statusCode': 400, 'error': 'target_number is required'}
    
    if not SIP_MEDIA_APP_ID:
        return {'statusCode': 400, 'error': 'SIP_MEDIA_APP_ID not configured'}
    
    if not CHIME_PHONE_NUMBER:
        return {'statusCode': 400, 'error': 'CHIME_PHONE_NUMBER not configured'}
    
    logger.info(f"Starting test {test_id} calling {target_number}")
    
    # Validate scenario
    validation_errors = validate_scenario(scenario)
    if validation_errors:
        return {
            'statusCode': 400,
            'error': 'Invalid scenario',
            'validation_errors': validation_errors
        }
    
    # Initialize test state
    test_state = {
        'test_id': test_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'scenario_name': scenario.get('name', 'unknown'),
        'target_number': target_number,
        'status': 'INITIATING',
        'started_at': datetime.now(timezone.utc).isoformat(),
    }
    
    # Save to test results table
    results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    results_table.put_item(Item=test_state)
    
    try:
        # Initiate the call via Chime SDK
        response = chime.create_sip_media_application_call(
            SipMediaApplicationId=SIP_MEDIA_APP_ID,
            FromPhoneNumber=CHIME_PHONE_NUMBER,
            ToPhoneNumber=target_number,
            SipHeaders={
                'X-Test-Id': test_id,
                'X-Scenario': scenario.get('name', 'unknown'),
            },
            ArgumentsMap={
                'test_id': test_id,
                'scenario': json.dumps(scenario),
            }
        )
        
        transaction_id = response.get('SipMediaApplicationCall', {}).get('TransactionId', '')
        
        # Update test state with transaction ID
        results_table.update_item(
            Key={'test_id': test_id, 'timestamp': test_state['timestamp']},
            UpdateExpression="SET #status = :status, transaction_id = :tid",
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'CALLING',
                ':tid': transaction_id
            }
        )
        
        # Initialize call state table for the call handler
        call_state_table = dynamodb.Table(CALL_STATE_TABLE)
        call_state_table.put_item(Item={
            'call_id': transaction_id,
            'test_id': test_id,
            'scenario_name': scenario.get('name', 'unknown'),
            'scenario_data': scenario,
            'status': 'INITIATING',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'current_step_index': 0,
            'conversation': [],
            'ttl': int(datetime.now(timezone.utc).timestamp()) + 3600,
        })
        
        logger.info(f"Call initiated: {transaction_id}")
        
        return {
            'statusCode': 200,
            'test_id': test_id,
            'transaction_id': transaction_id,
            'status': 'CALLING',
            'message': f'Test initiated, calling {target_number}'
        }
        
    except Exception as e:
        logger.error(f"Error initiating call: {e}")
        
        # Update status to failed
        results_table.update_item(
            Key={'test_id': test_id, 'timestamp': test_state['timestamp']},
            UpdateExpression="SET #status = :status, #error = :error",
            ExpressionAttributeNames={'#status': 'status', '#error': 'error'},
            ExpressionAttributeValues={
                ':status': 'FAILED',
                ':error': str(e)
            }
        )
        
        return {
            'statusCode': 500,
            'test_id': test_id,
            'error': str(e)
        }


def handle_check_status(event: Dict[str, Any]) -> Dict[str, Any]:
    """Check the status of a running test"""
    test_id = event.get('test_id', '')
    
    if not test_id:
        return {'statusCode': 400, 'error': 'test_id is required'}
    
    # Query test results table
    results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    response = results_table.query(
        KeyConditionExpression=Key('test_id').eq(test_id),
        ScanIndexForward=False,
        Limit=1
    )
    
    items = response.get('Items', [])
    if not items:
        return {'statusCode': 404, 'error': f'Test not found: {test_id}'}
    
    test = items[0]
    
    # If call is active, get live status from call state table
    if test.get('status') in ['CALLING', 'CONNECTED', 'IN_PROGRESS']:
        call_state_table = dynamodb.Table(CALL_STATE_TABLE)
        transaction_id = test.get('transaction_id', '')
        
        if transaction_id:
            call_response = call_state_table.get_item(Key={'call_id': transaction_id})
            call_state = call_response.get('Item', {})
            
            test['live_status'] = call_state.get('status', 'UNKNOWN')
            test['current_step'] = call_state.get('current_step_index', 0)
            test['conversation_length'] = len(call_state.get('conversation', []))
    
    return {
        'statusCode': 200,
        'test': test
    }


def handle_get_results(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get detailed test results"""
    test_id = event.get('test_id', '')
    include_recording = event.get('include_recording', False)
    
    if not test_id:
        return {'statusCode': 400, 'error': 'test_id is required'}
    
    # Get test from results table
    results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    response = results_table.query(
        KeyConditionExpression=Key('test_id').eq(test_id),
        ScanIndexForward=False,
        Limit=1
    )
    
    items = response.get('Items', [])
    if not items:
        return {'statusCode': 404, 'error': f'Test not found: {test_id}'}
    
    test = items[0]
    
    # Get full conversation from call state if available
    call_state_table = dynamodb.Table(CALL_STATE_TABLE)
    transaction_id = test.get('transaction_id', '')
    
    if transaction_id:
        call_response = call_state_table.get_item(Key={'call_id': transaction_id})
        call_state = call_response.get('Item', {})
        test['conversation'] = call_state.get('conversation', [])
    
    # Get recording URL if requested
    if include_recording and RECORDINGS_BUCKET:
        recording_prefix = f"recordings/{test_id}/"
        try:
            recordings = s3.list_objects_v2(
                Bucket=RECORDINGS_BUCKET,
                Prefix=recording_prefix
            )
            
            recording_files = [obj['Key'] for obj in recordings.get('Contents', [])]
            
            if recording_files:
                # Generate presigned URLs
                test['recordings'] = []
                for key in recording_files:
                    url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': RECORDINGS_BUCKET, 'Key': key},
                        ExpiresIn=3600
                    )
                    test['recordings'].append({
                        'key': key,
                        'url': url
                    })
        except Exception as e:
            logger.error(f"Error getting recordings: {e}")
    
    return {
        'statusCode': 200,
        'test': test
    }


def handle_list_tests(event: Dict[str, Any]) -> Dict[str, Any]:
    """List recent tests, optionally filtered by scenario"""
    scenario_name = event.get('scenario_name')
    limit = event.get('limit', 20)
    
    results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    if scenario_name:
        # Query by scenario using GSI
        response = results_table.query(
            IndexName='ScenarioIndex',
            KeyConditionExpression=Key('scenario_name').eq(scenario_name),
            ScanIndexForward=False,
            Limit=limit
        )
    else:
        # Scan for recent tests (not efficient, but OK for small tables)
        response = results_table.scan(Limit=limit)
    
    tests = response.get('Items', [])
    
    # Sort by timestamp descending
    tests.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return {
        'statusCode': 200,
        'tests': tests[:limit],
        'count': len(tests)
    }


def handle_cancel_test(event: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel an in-progress test"""
    test_id = event.get('test_id', '')
    
    if not test_id:
        return {'statusCode': 400, 'error': 'test_id is required'}
    
    # Get test info
    results_table = dynamodb.Table(TEST_RESULTS_TABLE)
    
    response = results_table.query(
        KeyConditionExpression=Key('test_id').eq(test_id),
        ScanIndexForward=False,
        Limit=1
    )
    
    items = response.get('Items', [])
    if not items:
        return {'statusCode': 404, 'error': f'Test not found: {test_id}'}
    
    test = items[0]
    transaction_id = test.get('transaction_id', '')
    
    if not transaction_id:
        return {'statusCode': 400, 'error': 'No active call to cancel'}
    
    try:
        # Update the call to hang up
        chime.update_sip_media_application_call(
            SipMediaApplicationId=SIP_MEDIA_APP_ID,
            TransactionId=transaction_id,
            Arguments={
                'action': 'hangup'
            }
        )
        
        # Update status
        results_table.update_item(
            Key={'test_id': test_id, 'timestamp': test['timestamp']},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': 'CANCELLED'}
        )
        
        return {
            'statusCode': 200,
            'message': f'Test {test_id} cancelled'
        }
        
    except Exception as e:
        logger.error(f"Error cancelling test: {e}")
        return {'statusCode': 500, 'error': str(e)}


def handle_provision_number(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Provision a phone number for the voice tester.
    
    This is a one-time setup operation.
    """
    area_code = event.get('area_code', '')
    country = event.get('country', 'US')
    
    try:
        # Search for available numbers
        search_response = chime.search_available_phone_numbers(
            AreaCode=area_code if area_code else None,
            Country=country,
            PhoneNumberType='Local',
            MaxResults=5
        )
        
        available = search_response.get('E164PhoneNumbers', [])
        
        if not available:
            return {
                'statusCode': 404,
                'error': 'No phone numbers available in that area'
            }
        
        # Order the first available number
        phone_number = available[0]
        
        order_response = chime.create_phone_number_order(
            ProductType='SipMediaApplicationDialIn',
            E164PhoneNumbers=[phone_number]
        )
        
        order_id = order_response.get('PhoneNumberOrder', {}).get('PhoneNumberOrderId', '')
        
        return {
            'statusCode': 200,
            'phone_number': phone_number,
            'order_id': order_id,
            'message': 'Phone number order created. Check order status for completion.',
            'available_numbers': available
        }
        
    except Exception as e:
        logger.error(f"Error provisioning number: {e}")
        return {'statusCode': 500, 'error': str(e)}


# =============================================================================
# Helper Functions
# =============================================================================

def validate_scenario(scenario: Dict[str, Any]) -> List[str]:
    """Validate a test scenario"""
    errors = []
    
    if not scenario.get('name'):
        errors.append("Scenario must have a name")
    
    steps = scenario.get('steps', [])
    if not steps:
        errors.append("Scenario must have at least one step")
    
    for i, step in enumerate(steps):
        if not step.get('id'):
            errors.append(f"Step {i} must have an id")
        if not step.get('action'):
            errors.append(f"Step {i} must have an action")
        
        action = step.get('action', '')
        if action not in ['speak', 'listen', 'dtmf', 'wait', 'hangup']:
            errors.append(f"Step {i} has invalid action: {action}")
    
    return errors
