#!/usr/bin/env python3
"""Analyze Amazon Connect instances and their contact flows."""

import boto3
import json

def analyze_instances():
    connect = boto3.client('connect')
    
    # Get all instances
    instances_response = connect.list_instances()
    
    results = {}
    
    for inst in instances_response['InstanceSummaryList']:
        instance_id = inst['Id']
        instance_name = inst.get('InstanceAlias', 'unnamed')
        
        print(f"\n{'=' * 70}")
        print(f"INSTANCE: {instance_name}")
        print(f"{'=' * 70}")
        print(f"ID: {instance_id}")
        print(f"Status: {inst['InstanceStatus']}")
        
        results[instance_name] = {
            'id': instance_id,
            'arn': inst['Arn'],
            'flows': [],
            'phone_numbers': []
        }
        
        # Get contact flows
        try:
            flows = connect.list_contact_flows(
                InstanceId=instance_id,
                ContactFlowTypes=['CONTACT_FLOW']
            )
            
            custom_flows = [
                f for f in flows['ContactFlowSummaryList'] 
                if 'Default' not in f['Name'] and 'Sample' not in f['Name']
            ]
            
            print(f"\nCustom Contact Flows ({len(custom_flows)}):")
            for flow in custom_flows:
                print(f"  - {flow['Name']}")
                print(f"    ID: {flow['Id']}")
                results[instance_name]['flows'].append({
                    'name': flow['Name'],
                    'id': flow['Id'],
                    'type': flow['ContactFlowType']
                })
                
        except Exception as e:
            print(f"  Error listing flows: {e}")
        
        # Get phone numbers
        try:
            numbers = connect.list_phone_numbers(InstanceId=instance_id)
            
            print(f"\nPhone Numbers:")
            for num in numbers.get('PhoneNumberSummaryList', []):
                phone = num['PhoneNumber']
                print(f"  - {phone} ({num.get('PhoneNumberType', 'N/A')})")
                results[instance_name]['phone_numbers'].append(phone)
                
        except Exception as e:
            print(f"  Error listing numbers: {e}")
    
    return results

def get_flow_details(instance_id: str, flow_id: str, flow_name: str):
    """Get detailed flow content."""
    connect = boto3.client('connect')
    
    try:
        response = connect.describe_contact_flow(
            InstanceId=instance_id,
            ContactFlowId=flow_id
        )
        
        flow = response['ContactFlow']
        content = json.loads(flow.get('Content', '{}'))
        
        print(f"\n--- Flow: {flow_name} ---")
        
        # Extract key info from flow
        actions = content.get('Actions', [])
        
        # Find prompts and Lex integrations
        prompts = []
        lex_bots = []
        
        for action in actions:
            action_type = action.get('Type', '')
            params = action.get('Parameters', {})
            
            if action_type == 'MessageParticipant':
                text = params.get('Text', '')
                if text:
                    prompts.append(text[:100])
                    
            elif action_type == 'ConnectParticipantWithLexBot':
                bot_name = params.get('LexBot', {}).get('Name', 'Unknown')
                lex_bots.append(bot_name)
        
        if prompts:
            print(f"  Voice Prompts: {len(prompts)}")
            for p in prompts[:3]:
                print(f"    - \"{p}...\"" if len(p) == 100 else f"    - \"{p}\"")
                
        if lex_bots:
            print(f"  Lex Bots: {lex_bots}")
            
        return {
            'prompts': prompts,
            'lex_bots': lex_bots,
            'action_count': len(actions)
        }
        
    except Exception as e:
        print(f"  Error getting flow details: {e}")
        return None

if __name__ == '__main__':
    print("Analyzing Amazon Connect Instances...")
    results = analyze_instances()
    
    print("\n" + "=" * 70)
    print("FLOW DETAILS")
    print("=" * 70)
    
    for instance_name, data in results.items():
        for flow in data['flows']:
            get_flow_details(data['id'], flow['id'], flow['name'])
    
    # Save results
    with open('connect_analysis.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n\nResults saved to connect_analysis.json")
