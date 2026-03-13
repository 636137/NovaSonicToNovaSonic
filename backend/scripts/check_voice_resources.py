#!/usr/bin/env python3
"""Check Chime SDK Voice resources for PSTN testing."""
import boto3

chime = boto3.client('chime-sdk-voice', region_name='us-east-1')

print('=== SIP Media Applications ===')
try:
    apps = chime.list_sip_media_applications()
    if apps.get('SipMediaApplications'):
        for app in apps['SipMediaApplications']:
            print(f"  {app['Name']} ({app['SipMediaApplicationId']})")
            print(f"    Endpoints: {app.get('Endpoints', [])}")
    else:
        print("  None found")
except Exception as e:
    print(f'  Error: {e}')

print('\n=== Voice Connectors ===')
try:
    vcs = chime.list_voice_connectors()
    if vcs.get('VoiceConnectors'):
        for vc in vcs['VoiceConnectors']:
            print(f"  {vc['Name']} ({vc['VoiceConnectorId']})")
    else:
        print("  None found")
except Exception as e:
    print(f'  Error: {e}')

print('\n=== Chime Phone Numbers ===')
try:
    numbers = chime.list_phone_numbers(MaxResults=10)
    if numbers.get('PhoneNumbers'):
        for num in numbers['PhoneNumbers']:
            print(f"  {num['E164PhoneNumber']} - Status: {num['Status']}, Type: {num.get('ProductType', 'N/A')}")
    else:
        print("  None found")
except Exception as e:
    print(f'  Error: {e}')

# Also check Connect's phone numbers
print('\n=== Amazon Connect Phone Numbers ===')
connect = boto3.client('connect', region_name='us-east-1')
instances = connect.list_instances()
for inst in instances['InstanceSummaryList']:
    try:
        numbers = connect.list_phone_numbers(InstanceId=inst['Id'])
        if numbers.get('PhoneNumberSummaryList'):
            print(f"  Instance: {inst.get('InstanceAlias', 'N/A')}")
            for num in numbers['PhoneNumberSummaryList']:
                print(f"    {num['PhoneNumber']} ({num.get('PhoneNumberType', 'N/A')})")
    except Exception as e:
        pass
