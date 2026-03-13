#!/usr/bin/env python3
"""Check CloudWatch logs for SIP Media Application Lambda."""
import boto3
from datetime import datetime

logs = boto3.client('logs', region_name='us-east-1')

log_group = '/aws/lambda/treasury-sip-media-app'

print(f'Checking logs for: {log_group}')
print('='*60)

try:
    streams = logs.describe_log_streams(
        logGroupName=log_group,
        orderBy='LastEventTime',
        descending=True,
        limit=3
    )
    
    for stream in streams['logStreams']:
        print(f"\nLog Stream: {stream['logStreamName']}")
        
        events = logs.get_log_events(
            logGroupName=log_group,
            logStreamName=stream['logStreamName'],
            limit=50
        )
        
        for event in events['events']:
            ts = datetime.fromtimestamp(event['timestamp']/1000)
            msg = event['message'].strip()
            # Truncate long messages
            if len(msg) > 200:
                msg = msg[:200] + '...'
            print(f'  [{ts.strftime("%H:%M:%S")}] {msg}')
            
except Exception as e:
    print(f'Error: {e}')
