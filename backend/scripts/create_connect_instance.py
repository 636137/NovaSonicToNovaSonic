#!/usr/bin/env python3
"""
Script to create and configure Amazon Connect instance for Census Survey
"""
import boto3
import json
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize AWS clients
connect_client = boto3.client('connect')
lex_client = boto3.client('lexv2-models')
lambda_client = boto3.client('lambda')

INSTANCE_ALIAS = 'CensusSurvey'
INSTANCE_TYPE = 'CONNECT_MANAGED'


def create_connect_instance():
    """Create Amazon Connect instance"""
    print("Creating Amazon Connect instance...")
    
    try:
        response = connect_client.create_instance(
            IdentityManagementType='CONNECT_MANAGED',
            InstanceAlias=INSTANCE_ALIAS,
            InboundCallsEnabled=True,
            OutboundCallsEnabled=False,
        )
        
        instance_id = response['Id']
        instance_arn = response['Arn']
        
        print(f"✓ Connect instance created: {instance_id}")
        print(f"✓ Instance ARN: {instance_arn}")
        
        # Wait for instance to be active
        print("Waiting for instance to become active...")
        while True:
            instance = connect_client.describe_instance(InstanceId=instance_id)
            status = instance['Instance']['InstanceStatus']
            
            if status == 'ACTIVE':
                print("✓ Instance is now active")
                break
            elif status == 'CREATION_FAILED':
                print("✗ Instance creation failed")
                return None
                
            time.sleep(10)
        
        return instance_id, instance_arn
        
    except connect_client.exceptions.ResourceConflictException:
        print("Instance already exists. Fetching existing instance...")
        instances = connect_client.list_instances()
        
        for instance in instances['InstanceSummaryList']:
            if instance['InstanceAlias'] == INSTANCE_ALIAS:
                print(f"✓ Found existing instance: {instance['Id']}")
                return instance['Id'], instance['Arn']
        
        print("✗ Could not find or create instance")
        return None
    
    except Exception as e:
        print(f"✗ Error creating instance: {str(e)}")
        return None


def create_lex_bot(lambda_arn, lex_role_arn):
    """Create and configure Lex bot"""
    print("\nCreating Lex bot...")
    
    try:
        # Read bot definition
        with open('lex/bot_definition.json', 'r') as f:
            bot_def = json.load(f)
        
        # Update role ARN
        bot_def['roleArn'] = lex_role_arn
        
        # Create bot
        response = lex_client.create_bot(
            botName=bot_def['name'],
            description=bot_def['description'],
            roleArn=bot_def['roleArn'],
            dataPrivacy=bot_def['dataPrivacy'],
            idleSessionTTLInSeconds=bot_def['idleSessionTTLInSeconds']
        )
        
        bot_id = response['botId']
        print(f"✓ Lex bot created: {bot_id}")
        
        # Wait for bot to be ready
        print("Waiting for bot to be ready...")
        max_wait = 60
        waited = 0
        while waited < max_wait:
            try:
                bot_status = lex_client.describe_bot(botId=bot_id)
                if bot_status['botStatus'] == 'Available':
                    print("✓ Bot is ready")
                    break
                time.sleep(5)
                waited += 5
            except Exception as e:
                time.sleep(5)
                waited += 5
        
        # Create bot locale with intents and slot types
        locale_data = bot_def['botLocales'][0]
        
        locale_response = lex_client.create_bot_locale(
            botId=bot_id,
            botVersion='DRAFT',
            localeId=locale_data['localeId'],
            description=locale_data['description'],
            nluIntentConfidenceThreshold=locale_data['nluIntentConfidenceThreshold'],
            voiceSettings=locale_data.get('voiceSettings', {})
        )
        
        print(f"✓ Bot locale created: {locale_data['localeId']}")
        
        # Wait for locale to be ready
        print("Waiting for bot locale to be ready...")
        max_wait = 60
        waited = 0
        while waited < max_wait:
            try:
                locale_status = lex_client.describe_bot_locale(
                    botId=bot_id,
                    botVersion='DRAFT',
                    localeId=locale_data['localeId']
                )
                if locale_status['botLocaleStatus'] in ['NotBuilt', 'ReadyExpressTesting']:
                    print("✓ Locale is ready")
                    break
                time.sleep(5)
                waited += 5
            except Exception as e:
                time.sleep(5)
                waited += 5
        
        # Create slot types
        for slot_type in locale_data.get('slotTypes', []):
            try:
                lex_client.create_slot_type(
                    botId=bot_id,
                    botVersion='DRAFT',
                    localeId=locale_data['localeId'],
                    slotTypeName=slot_type['slotTypeName'],
                    description=slot_type.get('description', ''),
                    slotTypeValues=slot_type['slotTypeValues'],
                    valueSelectionSetting=slot_type['valueSelectionSetting']
                )
                print(f"✓ Created slot type: {slot_type['slotTypeName']}")
            except Exception as e:
                print(f"⚠ Slot type {slot_type['slotTypeName']}: {str(e)}")
        
        # Create intents
        for intent in locale_data.get('intents', []):
            try:
                intent_params = {
                    'botId': bot_id,
                    'botVersion': 'DRAFT',
                    'localeId': locale_data['localeId'],
                    'intentName': intent['intentName'],
                    'description': intent.get('description', ''),
                    'sampleUtterances': intent.get('sampleUtterances', [])
                }
                
                if 'slots' in intent:
                    intent_params['slots'] = intent['slots']
                    intent_params['slotPriorities'] = intent.get('slotPriorities', [])
                
                if intent.get('fulfillmentCodeHook', {}).get('enabled'):
                    intent_params['fulfillmentCodeHook'] = {
                        'enabled': True
                    }
                
                lex_client.create_intent(**intent_params)
                print(f"✓ Created intent: {intent['intentName']}")
            except Exception as e:
                print(f"⚠ Intent {intent['intentName']}: {str(e)}")
        
        # Build bot
        print("Building bot...")
        lex_client.build_bot_locale(
            botId=bot_id,
            botVersion='DRAFT',
            localeId=locale_data['localeId']
        )
        
        print("✓ Lex bot build initiated")
        
        # Add Lambda permission for Lex
        try:
            lambda_client.add_permission(
                FunctionName=lambda_arn.split(':')[-1],
                StatementId=f'LexInvoke-{bot_id}',
                Action='lambda:InvokeFunction',
                Principal='lexv2.amazonaws.com',
                SourceArn=f"arn:aws:lex:{boto3.session.Session().region_name}:{boto3.client('sts').get_caller_identity()['Account']}:bot-alias/{bot_id}/*"
            )
            print("✓ Lambda permission added for Lex")
        except lambda_client.exceptions.ResourceConflictException:
            print("⚠ Lambda permission already exists")
        
        return bot_id
        
    except Exception as e:
        print(f"✗ Error creating Lex bot: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def configure_connect_instance(instance_id, recordings_bucket):
    """Configure Connect instance settings"""
    print(f"\nConfiguring Connect instance {instance_id}...")
    
    try:
        # Enable data storage
        connect_client.associate_instance_storage_config(
            InstanceId=instance_id,
            ResourceType='CALL_RECORDINGS',
            StorageConfig={
                'StorageType': 'S3',
                'S3Config': {
                    'BucketName': recordings_bucket,
                    'BucketPrefix': 'recordings'
                }
            }
        )
        print("✓ Call recordings storage configured")
        
        connect_client.associate_instance_storage_config(
            InstanceId=instance_id,
            ResourceType='CHAT_TRANSCRIPTS',
            StorageConfig={
                'StorageType': 'S3',
                'S3Config': {
                    'BucketName': recordings_bucket,
                    'BucketPrefix': 'transcripts'
                }
            }
        )
        print("✓ Chat transcripts storage configured")
        
        # Enable contact lens
        try:
            connect_client.update_instance_attribute(
                InstanceId=instance_id,
                AttributeType='CONTACT_LENS',
                Value='true'
            )
            print("✓ Contact Lens enabled")
        except Exception as e:
            print(f"⚠ Contact Lens: {str(e)}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error configuring instance: {str(e)}")
        return False


def import_contact_flows(instance_id, lambda_arn):
    """Import contact flows into Connect instance"""
    print(f"\nImporting contact flows...")
    
    flow_files = {
        'voice_survey_flow.json': 'Voice Survey Flow',
        'chat_survey_flow.json': 'Chat Survey Flow'
    }
    
    for filename, flow_name in flow_files.items():
        try:
            with open(f'contact_flows/{filename}', 'r') as f:
                flow_content = f.read()
            
            # Replace Lambda ARN placeholder
            flow_content = flow_content.replace('REPLACE_WITH_SURVEY_LAMBDA_ARN', lambda_arn)
            
            response = connect_client.create_contact_flow(
                InstanceId=instance_id,
                Name=flow_name,
                Type='CONTACT_FLOW',
                Content=flow_content,
                Description=f'Census survey contact flow - {filename}'
            )
            
            print(f"✓ Imported: {flow_name} ({response['ContactFlowId']})")
            
        except Exception as e:
            print(f"✗ Error importing {filename}: {str(e)}")


def get_stack_outputs():
    """Get outputs from CDK stack"""
    print("\nRetrieving CDK stack outputs...")
    
    cfn_client = boto3.client('cloudformation')
    
    try:
        response = cfn_client.describe_stacks(StackName='ConnectCensusStack')
        outputs = response['Stacks'][0]['Outputs']
        
        output_dict = {}
        for output in outputs:
            output_dict[output['OutputKey']] = output['OutputValue']
            print(f"  {output['OutputKey']}: {output['OutputValue']}")
        
        return output_dict
        
    except Exception as e:
        print(f"✗ Error retrieving stack outputs: {str(e)}")
        return None


def main():
    """Main execution"""
    print("=" * 60)
    print("Amazon Connect Census Survey Deployment")
    print("=" * 60)
    
    # Get CDK stack outputs
    outputs = get_stack_outputs()
    if not outputs:
        print("\n✗ Please deploy the CDK stack first: cdk deploy")
        return
    
    lambda_arn = outputs.get('SurveyLambdaArn')
    lex_lambda_arn = outputs.get('LexLambdaArn')
    lex_role_arn = outputs.get('LexRoleArn')
    recordings_bucket = outputs.get('RecordingsBucketName')
    
    # Create Connect instance
    result = create_connect_instance()
    if not result:
        return
    
    instance_id, instance_arn = result
    
    # Configure Connect instance
    configure_connect_instance(instance_id, recordings_bucket)
    
    # Create Lex bot
    bot_id = create_lex_bot(lex_lambda_arn, lex_role_arn)
    
    # Import contact flows
    if bot_id:
        import_contact_flows(instance_id, lambda_arn)
    
    # Print summary
    print("\n" + "=" * 60)
    print("Deployment Summary")
    print("=" * 60)
    print(f"Connect Instance ID: {instance_id}")
    print(f"Connect Instance ARN: {instance_arn}")
    if bot_id:
        print(f"Lex Bot ID: {bot_id}")
    print("\nNext Steps:")
    print("1. Access your Connect instance at:")
    print(f"   https://console.aws.amazon.com/connect/v2/app/instances/{instance_id}")
    print("2. Create a phone number and associate it with the Voice Survey Flow")
    print("3. Enable chat widget and associate it with the Chat Survey Flow")
    print("4. Test the survey flows")
    print("=" * 60)


if __name__ == '__main__':
    main()
