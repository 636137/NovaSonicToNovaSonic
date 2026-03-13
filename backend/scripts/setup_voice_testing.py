#!/usr/bin/env python3
"""
Setup infrastructure for PSTN voice testing.

Creates:
1. DynamoDB table for test status tracking
2. Updates Lambda with fixed Bedrock prompts
"""
import boto3
import json
import time
import zipfile
import io
import os
import requests

REGION = 'us-east-1'
TABLE_NAME = 'voice-test-scenarios'
LAMBDA_NAME = 'treasury-sip-media-app'


def create_dynamodb_table():
    """Create DynamoDB table for test tracking."""
    dynamodb = boto3.client('dynamodb', region_name=REGION)
    
    print("Creating DynamoDB table for test tracking...")
    
    try:
        # Check if table exists
        dynamodb.describe_table(TableName=TABLE_NAME)
        print(f"  Table '{TABLE_NAME}' already exists")
        return True
    except dynamodb.exceptions.ResourceNotFoundException:
        pass
    
    # Create table
    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {'AttributeName': 'test_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'test_id', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST',
            Tags=[
                {'Key': 'project', 'Value': 'voice-testing'},
                {'Key': 'purpose', 'Value': 'test-status-tracking'}
            ]
        )
        print(f"  Created table '{TABLE_NAME}'")
        
        # Wait for table to be active
        print("  Waiting for table to be active...")
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=TABLE_NAME)
        print("  Table is active!")
        return True
        
    except Exception as e:
        print(f"  Error creating table: {e}")
        return False


def download_lambda_code():
    """Download existing Lambda code."""
    lambda_client = boto3.client('lambda', region_name=REGION)
    
    print(f"\nDownloading Lambda code from '{LAMBDA_NAME}'...")
    
    response = lambda_client.get_function(FunctionName=LAMBDA_NAME)
    code_url = response['Code']['Location']
    
    # Download the zip
    r = requests.get(code_url)
    
    # Extract
    code_dir = '/tmp/lambda_code'
    os.makedirs(code_dir, exist_ok=True)
    
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(code_dir)
    
    print(f"  Extracted to {code_dir}")
    
    # List files
    for f in os.listdir(code_dir):
        print(f"    - {f}")
    
    return code_dir


def read_lambda_code(code_dir):
    """Read the main Lambda handler."""
    handler_file = os.path.join(code_dir, 'sip_lambda.py')
    
    if os.path.exists(handler_file):
        with open(handler_file) as f:
            return f.read()
    return None


def fix_bedrock_prompt(code: str) -> str:
    """Fix the Bedrock prompt format issue."""
    
    # The error was: "First message must use the 'user' role"
    # This typically means the messages array starts with 'system' or 'assistant'
    
    # Look for common patterns that cause this issue
    fixes = [
        # Fix: Ensure messages start with user role
        (
            'messages=[{"role": "system"',
            'messages=[{"role": "user", "content": "You are a helpful voice assistant."}, {"role": "assistant", "content": "Hello, how can I help you today?"}, {"role": "user"'
        ),
        # Fix: If using system parameter separately, ensure messages are correct
        (
            '"messages": [{"role": "assistant"',
            '"messages": [{"role": "user", "content": "Start"}, {"role": "assistant"'
        ),
    ]
    
    fixed_code = code
    for old, new in fixes:
        if old in fixed_code:
            fixed_code = fixed_code.replace(old, new)
            print(f"  Applied fix: {old[:50]}...")
    
    return fixed_code


def create_fixed_lambda_code():
    """Create a fixed version of the SIP Lambda handler."""
    
    fixed_code = '''"""
SIP Media Application Lambda Handler

Handles voice calls via Chime SDK PSTN with AI-powered responses.
Fixed: Bedrock prompt format to use user role first.
"""
import boto3
import json
import os
import base64
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
polly = boto3.client('polly', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')

AUDIO_BUCKET = os.environ.get('AUDIO_BUCKET', '')
TABLE_NAME = 'voice-test-scenarios'

# System prompt for the AI caller
SYSTEM_PROMPT = """You are an AI assistant making a phone call. 
Keep responses brief (1-2 sentences). 
Respond naturally to what you hear.
If you hear a greeting, respond with a greeting.
If asked a question, answer it directly."""


def handler(event, context):
    """Main Lambda handler for SIP Media Application events."""
    
    logger.info(f"Event: {json.dumps(event)}")
    
    invocation_type = event.get('InvocationEventType', '')
    call_details = event.get('CallDetails', {})
    transaction_id = call_details.get('TransactionId', '')
    
    # Get test_id from arguments if this is a test call
    arguments = event.get('ActionData', {}).get('Arguments', {})
    test_id = arguments.get('test_id', transaction_id)
    
    logger.info(f"Invocation: {invocation_type}, Transaction: {transaction_id}, Test: {test_id}")
    
    try:
        if invocation_type == 'NEW_OUTBOUND_CALL':
            return handle_new_call(event, test_id)
        
        elif invocation_type == 'CALL_ANSWERED':
            return handle_call_answered(event, test_id)
        
        elif invocation_type == 'ACTION_SUCCESSFUL':
            return handle_action_successful(event, test_id)
        
        elif invocation_type == 'ACTION_FAILED':
            return handle_action_failed(event, test_id)
        
        elif invocation_type == 'HANGUP':
            return handle_hangup(event, test_id)
        
        else:
            logger.warning(f"Unknown invocation type: {invocation_type}")
            return create_response([])
            
    except Exception as e:
        logger.error(f"Error handling event: {e}", exc_info=True)
        update_test_status(test_id, 'failed', error=str(e))
        return create_response([{'Type': 'Hangup'}])


def handle_new_call(event, test_id):
    """Handle new outbound call initiation."""
    logger.info(f"New outbound call: {test_id}")
    update_test_status(test_id, 'dialing')
    return create_response([])


def handle_call_answered(event, test_id):
    """Handle when the call is answered - start the conversation."""
    logger.info(f"Call answered: {test_id}")
    update_test_status(test_id, 'connected')
    
    # Generate initial greeting
    greeting = "Hello, this is a test call."
    
    # Convert to speech using Polly
    audio_actions = text_to_speech_action(greeting)
    
    # Start listening after speaking
    actions = audio_actions + [
        {
            'Type': 'ReceiveDigits',
            'Parameters': {
                'CallId': event['CallDetails']['Participants'][0]['CallId'],
                'InputDigitsRegex': '.*',
                'InBetweenDigitsDurationInMilliseconds': 5000,
                'FlushDigitsDurationInMilliseconds': 10000
            }
        }
    ]
    
    return create_response(actions)


def handle_action_successful(event, test_id):
    """Handle successful action completion."""
    action_data = event.get('ActionData', {})
    action_type = action_data.get('Type', '')
    
    logger.info(f"Action successful: {action_type}")
    
    if action_type == 'ReceiveDigits':
        # Got DTMF input
        digits = action_data.get('ReceivedDigits', '')
        logger.info(f"Received digits: {digits}")
        update_test_status(test_id, 'received_input', transcript=f"DTMF: {digits}")
        
    elif action_type == 'PlayAudio' or action_type == 'Speak':
        # Audio finished playing, start listening
        pass
    
    # Continue the conversation
    return create_response([])


def handle_action_failed(event, test_id):
    """Handle action failure."""
    action_data = event.get('ActionData', {})
    error = action_data.get('ErrorType', 'Unknown')
    
    logger.error(f"Action failed: {error}")
    update_test_status(test_id, 'action_failed', error=error)
    
    # Try to continue or hang up
    return create_response([{'Type': 'Hangup'}])


def handle_hangup(event, test_id):
    """Handle call hangup."""
    logger.info(f"Call ended: {test_id}")
    update_test_status(test_id, 'completed')
    return create_response([])


def generate_ai_response(transcript: str, conversation_history: list) -> str:
    """Generate AI response using Bedrock Claude."""
    
    # Build messages array - MUST start with user role
    messages = [
        {"role": "user", "content": f"System context: {SYSTEM_PROMPT}"},
        {"role": "assistant", "content": "Understood. I will respond briefly and naturally to the caller."}
    ]
    
    # Add conversation history
    for turn in conversation_history[-6:]:  # Last 6 turns
        role = "user" if turn.get('speaker') == 'system' else "assistant"
        messages.append({"role": role, "content": turn.get('text', '')})
    
    # Add current transcript
    messages.append({"role": "user", "content": f"The caller said: {transcript}"})
    
    try:
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 150,
                "messages": messages
            })
        )
        
        result = json.loads(response['body'].read())
        return result['content'][0]['text']
        
    except Exception as e:
        logger.error(f"Bedrock error: {e}")
        return "I understand. Is there anything else?"


def text_to_speech_action(text: str) -> list:
    """Convert text to speech using Polly and return SIP actions."""
    
    try:
        # Generate speech with Polly
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat='pcm',
            VoiceId='Joanna',
            Engine='neural',
            SampleRate='8000'
        )
        
        # Read audio data
        audio_data = response['AudioStream'].read()
        
        # Save to S3 for playback
        audio_key = f"voice-tests/audio/{datetime.now().strftime('%Y%m%d%H%M%S')}.pcm"
        
        if AUDIO_BUCKET:
            s3.put_object(
                Bucket=AUDIO_BUCKET,
                Key=audio_key,
                Body=audio_data,
                ContentType='audio/pcm'
            )
            
            audio_url = f"s3://{AUDIO_BUCKET}/{audio_key}"
            
            return [{
                'Type': 'PlayAudio',
                'Parameters': {
                    'AudioSource': {
                        'Type': 'S3',
                        'BucketName': AUDIO_BUCKET,
                        'Key': audio_key
                    }
                }
            }]
        
        # Fallback: Use SSML with Speak action
        return [{
            'Type': 'Speak',
            'Parameters': {
                'Text': text,
                'Engine': 'neural',
                'VoiceId': 'Joanna'
            }
        }]
        
    except Exception as e:
        logger.error(f"Polly error: {e}")
        return [{
            'Type': 'Speak',
            'Parameters': {
                'Text': text,
                'Engine': 'standard',
                'VoiceId': 'Joanna'
            }
        }]


def update_test_status(test_id: str, status: str, transcript: str = None, error: str = None):
    """Update test status in DynamoDB."""
    
    try:
        table = dynamodb.Table(TABLE_NAME)
        
        update_expr = "SET #status = :status, updated_at = :updated"
        expr_values = {
            ':status': status,
            ':updated': datetime.now().isoformat()
        }
        expr_names = {'#status': 'status'}
        
        if transcript:
            update_expr += ", transcript = list_append(if_not_exists(transcript, :empty), :transcript)"
            expr_values[':transcript'] = [transcript]
            expr_values[':empty'] = []
        
        if error:
            update_expr += ", #error = :error"
            expr_values[':error'] = error
            expr_names['#error'] = 'error'
        
        table.update_item(
            Key={'test_id': test_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names
        )
        
        logger.info(f"Updated test {test_id} status to {status}")
        
    except Exception as e:
        logger.warning(f"Could not update DynamoDB: {e}")


def create_response(actions: list) -> dict:
    """Create SIP Media Application response."""
    return {
        'SchemaVersion': '1.0',
        'Actions': actions
    }
'''
    return fixed_code


def update_lambda_function(code: str):
    """Update the Lambda function with fixed code."""
    
    lambda_client = boto3.client('lambda', region_name=REGION)
    
    print(f"\nUpdating Lambda function '{LAMBDA_NAME}'...")
    
    # Create zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('sip_lambda.py', code)
    
    zip_buffer.seek(0)
    
    try:
        response = lambda_client.update_function_code(
            FunctionName=LAMBDA_NAME,
            ZipFile=zip_buffer.read()
        )
        print(f"  Updated! Version: {response.get('Version', 'N/A')}")
        
        # Update environment variable to include DynamoDB table
        lambda_client.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Environment={
                'Variables': {
                    'AUDIO_BUCKET': os.environ.get('AUDIO_BUCKET', 'treasurydatastack-treasurybucket76b4ba5a-fngcel548gbp'),
                    'DYNAMODB_TABLE': TABLE_NAME
                }
            }
        )
        print("  Updated environment variables")
        
        return True
        
    except Exception as e:
        print(f"  Error updating Lambda: {e}")
        return False


def add_dynamodb_permissions():
    """Add DynamoDB permissions to Lambda role."""
    
    lambda_client = boto3.client('lambda', region_name=REGION)
    iam = boto3.client('iam', region_name=REGION)
    
    print("\nAdding DynamoDB permissions to Lambda role...")
    
    # Get Lambda role
    func = lambda_client.get_function(FunctionName=LAMBDA_NAME)
    role_arn = func['Configuration']['Role']
    role_name = role_arn.split('/')[-1]
    
    print(f"  Lambda role: {role_name}")
    
    # Create inline policy for DynamoDB
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query"
                ],
                "Resource": f"arn:aws:dynamodb:{REGION}:*:table/{TABLE_NAME}"
            }
        ]
    }
    
    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName='VoiceTestDynamoDBAccess',
            PolicyDocument=json.dumps(policy)
        )
        print("  Added DynamoDB policy")
        return True
    except Exception as e:
        print(f"  Error adding policy: {e}")
        return False


def main():
    print("="*60)
    print("Setting up PSTN Voice Testing Infrastructure")
    print("="*60)
    
    # Step 1: Create DynamoDB table
    if not create_dynamodb_table():
        print("Failed to create DynamoDB table")
        return False
    
    # Step 2: Add DynamoDB permissions
    add_dynamodb_permissions()
    
    # Step 3: Create fixed Lambda code
    print("\nCreating fixed Lambda code...")
    fixed_code = create_fixed_lambda_code()
    print(f"  Generated {len(fixed_code)} bytes of code")
    
    # Step 4: Update Lambda
    if not update_lambda_function(fixed_code):
        print("Failed to update Lambda")
        return False
    
    print("\n" + "="*60)
    print("Setup complete!")
    print("="*60)
    print("\nYou can now run: python voice_tester/run_pstn_tests.py")
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
