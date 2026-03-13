#!/usr/bin/env python3
"""Update Lambda environment after code deployment."""
import boto3
import time

lambda_client = boto3.client('lambda', region_name='us-east-1')

print('Waiting for Lambda to be ready...')
for i in range(10):
    try:
        response = lambda_client.get_function(FunctionName='treasury-sip-media-app')
        state = response['Configuration'].get('State', 'Unknown')
        last_update = response['Configuration'].get('LastUpdateStatus', 'Unknown')
        print(f'  State: {state}, LastUpdate: {last_update}')
        if last_update == 'Successful':
            break
    except Exception as e:
        print(f'  Error: {e}')
    time.sleep(2)

print('Updating environment variables...')
try:
    lambda_client.update_function_configuration(
        FunctionName='treasury-sip-media-app',
        Environment={
            'Variables': {
                'AUDIO_BUCKET': 'treasurydatastack-treasurybucket76b4ba5a-fngcel548gbp',
                'DYNAMODB_TABLE': 'voice-test-scenarios'
            }
        }
    )
    print('Done!')
except Exception as e:
    print(f'Error: {e}')
