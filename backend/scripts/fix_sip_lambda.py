#!/usr/bin/env python3
"""Fix SIP Lambda to use Speak action instead of PlayAudio."""

import boto3
import zipfile
import io

LAMBDA_CODE = '''"""
SIP Media Application Lambda Handler

Handles voice calls via Chime SDK PSTN with AI-powered responses.
Uses Speak action for TTS (simpler and more reliable than PlayAudio).
"""
import boto3
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
TABLE_NAME = "voice-test-scenarios"


def handler(event, context):
    """Main Lambda handler for SIP Media Application events."""
    
    logger.info(f"Event: {json.dumps(event)}")
    
    invocation_type = event.get("InvocationEventType", "")
    call_details = event.get("CallDetails", {})
    transaction_id = call_details.get("TransactionId", "")
    
    # Get test_id from action arguments or transaction
    arguments = event.get("ActionData", {}).get("Arguments", {})
    test_id = arguments.get("test_id", transaction_id)
    
    logger.info(f"Invocation: {invocation_type}, Transaction: {transaction_id}")
    
    try:
        if invocation_type == "NEW_OUTBOUND_CALL":
            update_test_status(test_id, "dialing")
            return create_response([])
        
        elif invocation_type == "RINGING":
            update_test_status(test_id, "ringing")
            return create_response([])
        
        elif invocation_type == "CALL_ANSWERED":
            update_test_status(test_id, "connected")
            call_id = call_details.get("Participants", [{}])[0].get("CallId", "")
            
            # Use Speak action with neural voice
            return create_response([
                {
                    "Type": "Speak",
                    "Parameters": {
                        "Text": "Hello, this is an automated test call. Please say something or press any digit.",
                        "CallId": call_id,
                        "Engine": "neural",
                        "VoiceId": "Joanna"
                    }
                },
                {
                    "Type": "ReceiveDigits",
                    "Parameters": {
                        "CallId": call_id,
                        "InputDigitsRegex": ".*",
                        "InBetweenDigitsDurationInMilliseconds": 3000,
                        "FlushDigitsDurationInMilliseconds": 5000
                    }
                }
            ])
        
        elif invocation_type == "ACTION_SUCCESSFUL":
            action_type = event.get("ActionData", {}).get("Type", "")
            logger.info(f"Action successful: {action_type}")
            
            if action_type == "ReceiveDigits":
                digits = event.get("ActionData", {}).get("ReceivedDigits", "timeout")
                update_test_status(test_id, "received_input", transcript=f"DTMF: {digits}")
                
                call_id = call_details.get("Participants", [{}])[0].get("CallId", "")
                return create_response([
                    {
                        "Type": "Speak",
                        "Parameters": {
                            "Text": "Thank you for your response. This test is complete. Goodbye.",
                            "CallId": call_id,
                            "Engine": "neural",
                            "VoiceId": "Joanna"
                        }
                    },
                    {
                        "Type": "Hangup",
                        "Parameters": {
                            "SipResponseCode": "0"
                        }
                    }
                ])
            
            elif action_type == "Speak":
                # Speech finished, continue with next action
                return create_response([])
            
            return create_response([])
        
        elif invocation_type == "ACTION_FAILED":
            error = event.get("ActionData", {}).get("ErrorType", "Unknown")
            error_info = event.get("ActionData", {}).get("ErrorMessage", "")
            logger.error(f"Action failed: {error} - {error_info}")
            update_test_status(test_id, "failed", error=f"{error}: {error_info}")
            return create_response([{"Type": "Hangup", "Parameters": {"SipResponseCode": "0"}}])
        
        elif invocation_type == "HANGUP":
            update_test_status(test_id, "completed")
            return create_response([])
        
        else:
            logger.info(f"Unhandled event type: {invocation_type}")
            return create_response([])
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        update_test_status(test_id, "failed", error=str(e))
        return create_response([{"Type": "Hangup", "Parameters": {"SipResponseCode": "0"}}])


def update_test_status(test_id: str, status: str, error: str = None, transcript: str = None):
    """Update test status in DynamoDB."""
    try:
        table = dynamodb.Table(TABLE_NAME)
        update_expr = "SET #status = :status, updated_at = :ts"
        expr_values = {
            ":status": status,
            ":ts": datetime.now().isoformat()
        }
        expr_names = {"#status": "status"}
        
        if error:
            update_expr += ", error_message = :err"
            expr_values[":err"] = error
            
        if transcript:
            update_expr += ", transcript = :tx"
            expr_values[":tx"] = transcript
        
        table.update_item(
            Key={"test_id": test_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values
        )
        logger.info(f"Updated {test_id} to {status}")
    except Exception as e:
        logger.error(f"DynamoDB error: {e}")


def create_response(actions: list) -> dict:
    """Create SIP Media Application response."""
    return {
        "SchemaVersion": "1.0",
        "Actions": actions
    }
'''


def main():
    print("Updating SIP Lambda...")
    
    # Create zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('sip_lambda.py', LAMBDA_CODE)
    
    zip_bytes = zip_buffer.getvalue()
    print(f"Created zip: {len(zip_bytes)} bytes")
    
    # Update Lambda
    lmb = boto3.client('lambda', region_name='us-east-1')
    response = lmb.update_function_code(
        FunctionName='treasury-sip-media-app',
        ZipFile=zip_bytes
    )
    print(f"Lambda updated: {response['LastUpdateStatus']}")
    
    # Wait for update
    import time
    for i in range(30):
        fn = lmb.get_function_configuration(FunctionName='treasury-sip-media-app')
        status = fn.get('LastUpdateStatus', 'Unknown')
        if status == 'Successful':
            print("Lambda ready!")
            return
        elif status == 'Failed':
            print(f"Update failed: {fn.get('LastUpdateStatusReason', 'Unknown')}")
            return
        print(f"Waiting... ({status})")
        time.sleep(2)
    
    print("Timeout waiting for Lambda")


if __name__ == "__main__":
    main()
