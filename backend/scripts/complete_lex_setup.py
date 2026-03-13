#!/usr/bin/env python3
"""
Script to complete Lex bot configuration
"""
import boto3
import json
import time
import os
import sys

lex_client = boto3.client('lexv2-models')
lambda_client = boto3.client('lambda')

BOT_ID = 'JFJLA39AXI'  # Existing bot that was created


def complete_lex_bot_setup():
    """Complete the Lex bot setup with locale, slot types, and intents"""
    print("=" * 60)
    print("Completing Lex Bot Configuration")
    print("=" * 60)
    print(f"\nBot ID: {BOT_ID}")
    
    try:
        # Check bot status
        print("\nChecking bot status...")
        bot = lex_client.describe_bot(botId=BOT_ID)
        print(f"Bot Status: {bot['botStatus']}")
        
        # Read bot definition
        with open('lex/bot_definition.json', 'r') as f:
            bot_def = json.load(f)
        
        locale_data = bot_def['botLocales'][0]
        locale_id = locale_data['localeId']
        
        # Check if locale already exists
        print(f"\nChecking if locale {locale_id} exists...")
        try:
            locale = lex_client.describe_bot_locale(
                botId=BOT_ID,
                botVersion='DRAFT',
                localeId=locale_id
            )
            print(f"✓ Locale exists: {locale['botLocaleStatus']}")
        except lex_client.exceptions.ResourceNotFoundException:
            print("Locale not found, creating it...")
            
            # Wait for bot to be ready
            print("Waiting for bot to be ready...")
            for i in range(20):
                bot = lex_client.describe_bot(botId=BOT_ID)
                if bot['botStatus'] == 'Available':
                    print("✓ Bot is ready")
                    break
                print(f"  Waiting... (attempt {i+1}/20)")
                time.sleep(5)
            
            # Create locale
            lex_client.create_bot_locale(
                botId=BOT_ID,
                botVersion='DRAFT',
                localeId=locale_id,
                description=locale_data['description'],
                nluIntentConfidenceThreshold=locale_data['nluIntentConfidenceThreshold'],
                voiceSettings=locale_data.get('voiceSettings', {})
            )
            print(f"✓ Locale created")
            
            # Wait for locale to be ready
            print("Waiting for locale to be ready...")
            for i in range(20):
                locale = lex_client.describe_bot_locale(
                    botId=BOT_ID,
                    botVersion='DRAFT',
                    localeId=locale_id
                )
                if locale['botLocaleStatus'] in ['NotBuilt', 'ReadyExpressTesting']:
                    print("✓ Locale is ready")
                    break
                print(f"  Waiting... {locale['botLocaleStatus']} (attempt {i+1}/20)")
                time.sleep(5)
        
        # Create slot types
        print("\nCreating slot types...")
        for slot_type in locale_data.get('slotTypes', []):
            try:
                lex_client.create_slot_type(
                    botId=BOT_ID,
                    botVersion='DRAFT',
                    localeId=locale_id,
                    slotTypeName=slot_type['slotTypeName'],
                    description=slot_type.get('description', ''),
                    slotTypeValues=slot_type['slotTypeValues'],
                    valueSelectionSetting=slot_type['valueSelectionSetting']
                )
                print(f"  ✓ {slot_type['slotTypeName']}")
            except lex_client.exceptions.ConflictException:
                print(f"  ⚠ {slot_type['slotTypeName']} already exists")
            except Exception as e:
                print(f"  ✗ {slot_type['slotTypeName']}: {str(e)}")
        
        # Create intents
        print("\nCreating intents...")
        for intent in locale_data.get('intents', []):
            try:
                intent_params = {
                    'botId': BOT_ID,
                    'botVersion': 'DRAFT',
                    'localeId': locale_id,
                    'intentName': intent['intentName'],
                    'description': intent.get('description', ''),
                    'sampleUtterances': intent.get('sampleUtterances', [])
                }
                
                if 'slots' in intent:
                    intent_params['slotPriorities'] = intent.get('slotPriorities', [])
                    # Create each slot
                    for slot in intent['slots']:
                        try:
                            intent_params['slots'] = intent['slots']
                        except:
                            pass
                
                if intent.get('fulfillmentCodeHook', {}).get('enabled'):
                    intent_params['fulfillmentCodeHook'] = {'enabled': True}
                
                lex_client.create_intent(**intent_params)
                print(f"  ✓ {intent['intentName']}")
            except lex_client.exceptions.ConflictException:
                print(f"  ⚠ {intent['intentName']} already exists")
            except Exception as e:
                print(f"  ✗ {intent['intentName']}: {str(e)}")
        
        # Build bot
        print("\nBuilding bot...")
        try:
            lex_client.build_bot_locale(
                botId=BOT_ID,
                botVersion='DRAFT',
                localeId=locale_id
            )
            print("✓ Bot build initiated")
            
            # Wait for build to complete
            print("Waiting for build to complete...")
            for i in range(30):
                locale = lex_client.describe_bot_locale(
                    botId=BOT_ID,
                    botVersion='DRAFT',
                    localeId=locale_id
                )
                status = locale['botLocaleStatus']
                if status == 'Built' or status == 'ReadyExpressTesting':
                    print("✓ Bot built successfully")
                    break
                elif status == 'Failed':
                    print("✗ Bot build failed")
                    break
                print(f"  Building... {status} (attempt {i+1}/30)")
                time.sleep(10)
        except Exception as e:
            print(f"⚠ Build error: {str(e)}")
        
        # Add Lambda permission for Lex
        print("\nConfiguring Lambda permissions...")
        try:
            # Get Lambda ARN from stack outputs
            import boto3
            cfn = boto3.client('cloudformation')
            response = cfn.describe_stacks(StackName='ConnectCensusStack')
            outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0]['Outputs']}
            lex_lambda_arn = outputs.get('LexLambdaArn')
            
            lambda_client.add_permission(
                FunctionName=lex_lambda_arn.split(':')[-1],
                StatementId=f'LexInvoke-{BOT_ID}',
                Action='lambda:InvokeFunction',
                Principal='lexv2.amazonaws.com',
                SourceArn=f"arn:aws:lex:us-east-1:{boto3.client('sts').get_caller_identity()['Account']}:bot-alias/{BOT_ID}/*"
            )
            print("✓ Lambda permission added")
        except lambda_client.exceptions.ConflictException:
            print("⚠ Lambda permission already exists")
        except Exception as e:
            print(f"⚠ Lambda permission: {str(e)}")
        
        print("\n" + "=" * 60)
        print("Lex Bot Configuration Complete!")
        print("=" * 60)
        print(f"Bot ID: {BOT_ID}")
        print(f"Locale: {locale_id}")
        print("\nYou can now test the bot in the AWS Console:")
        print(f"https://console.aws.amazon.com/lexv2/home?region=us-east-1#bot/{BOT_ID}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = complete_lex_bot_setup()
    sys.exit(0 if success else 1)
