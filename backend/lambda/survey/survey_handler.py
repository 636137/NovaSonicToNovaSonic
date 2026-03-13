import json
import os
import boto3
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['SURVEY_TABLE']
table = dynamodb.Table(table_name)


def lambda_handler(event, context):
    """
    Lambda function to handle survey responses from Amazon Connect
    """
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract contact information
        contact_id = event.get('Details', {}).get('ContactData', {}).get('ContactId', 'unknown')
        attributes = event.get('Details', {}).get('ContactData', {}).get('Attributes', {})
        
        # Get survey responses from attributes
        survey_data = {
            'contact_id': contact_id,
            'timestamp': datetime.utcnow().isoformat(),
            'household_size': attributes.get('household_size', ''),
            'primary_language': attributes.get('primary_language', ''),
            'employment_status': attributes.get('employment_status', ''),
            'age_range': attributes.get('age_range', ''),
            'housing_type': attributes.get('housing_type', ''),
            'channel': attributes.get('channel', 'voice'),
            'survey_complete': attributes.get('survey_complete', 'false')
        }
        
        # Save to DynamoDB
        table.put_item(Item=survey_data)
        
        return {
            'statusCode': 200,
            'success': True,
            'message': 'Survey data saved successfully',
            'contact_id': contact_id
        }
        
    except Exception as e:
        print(f"Error processing survey: {str(e)}")
        return {
            'statusCode': 500,
            'success': False,
            'message': f'Error: {str(e)}'
        }


def get_survey_stats(event, context):
    """
    Lambda function to retrieve survey statistics
    """
    try:
        response = table.scan()
        items = response.get('Items', [])
        
        stats = {
            'total_surveys': len(items),
            'completed_surveys': len([i for i in items if i.get('survey_complete') == 'true']),
            'channels': {
                'voice': len([i for i in items if i.get('channel') == 'voice']),
                'chat': len([i for i in items if i.get('channel') == 'chat'])
            }
        }
        
        return {
            'statusCode': 200,
            'body': json.dumps(stats)
        }
        
    except Exception as e:
        print(f"Error retrieving stats: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
