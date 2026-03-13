#!/usr/bin/env python3
"""
Script to test the Census Survey system
"""
import boto3
import json
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
connect_client = boto3.client('connect')


def test_dynamodb_access(table_name):
    """Test DynamoDB table access"""
    print(f"Testing DynamoDB table: {table_name}")
    
    try:
        table = dynamodb.Table(table_name)
        
        # Put test item
        test_item = {
            'contact_id': f'test_{datetime.utcnow().timestamp()}',
            'timestamp': datetime.utcnow().isoformat(),
            'household_size': '3',
            'primary_language': 'English',
            'employment_status': 'employed',
            'age_range': '35 to 54',
            'housing_type': 'house',
            'survey_complete': 'true',
            'test': True
        }
        
        table.put_item(Item=test_item)
        print("✓ Test item written to DynamoDB")
        
        # Scan for test items
        response = table.scan(
            FilterExpression='attribute_exists(#t)',
            ExpressionAttributeNames={'#t': 'test'}
        )
        
        print(f"✓ Found {len(response['Items'])} test items")
        
        # Clean up test items
        for item in response['Items']:
            table.delete_item(
                Key={
                    'contact_id': item['contact_id'],
                    'timestamp': item['timestamp']
                }
            )
        print("✓ Test items cleaned up")
        
        return True
        
    except Exception as e:
        print(f"✗ DynamoDB test failed: {str(e)}")
        return False


def test_lambda_function(function_name):
    """Test Lambda function"""
    print(f"\nTesting Lambda function: {function_name}")
    
    lambda_client = boto3.client('lambda')
    
    try:
        test_event = {
            'Details': {
                'ContactData': {
                    'ContactId': 'test-contact-123',
                    'Attributes': {
                        'household_size': '4',
                        'primary_language': 'Spanish',
                        'employment_status': 'employed',
                        'age_range': '18 to 34',
                        'housing_type': 'apartment',
                        'survey_complete': 'true',
                        'channel': 'voice'
                    }
                }
            }
        }
        
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(test_event)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"✓ Lambda function executed: {result}")
        
        return result.get('success', False)
        
    except Exception as e:
        print(f"✗ Lambda test failed: {str(e)}")
        return False


def list_connect_instances():
    """List all Connect instances"""
    print("\nListing Connect instances...")
    
    try:
        response = connect_client.list_instances()
        
        if not response['InstanceSummaryList']:
            print("No Connect instances found")
            return
        
        for instance in response['InstanceSummaryList']:
            print(f"\nInstance: {instance['InstanceAlias']}")
            print(f"  ID: {instance['Id']}")
            print(f"  ARN: {instance['Arn']}")
            print(f"  Status: {instance['InstanceStatus']}")
            
            # Get instance details
            details = connect_client.describe_instance(InstanceId=instance['Id'])
            print(f"  Created: {details['Instance']['CreatedTime']}")
            
        return True
        
    except Exception as e:
        print(f"✗ Error listing instances: {str(e)}")
        return False


def get_stack_outputs():
    """Get CloudFormation stack outputs"""
    print("\nRetrieving stack outputs...")
    
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
        print(f"✗ Error: {str(e)}")
        return None


def main():
    """Run all tests"""
    print("=" * 60)
    print("Census Survey System Tests")
    print("=" * 60)
    
    # Get stack outputs
    outputs = get_stack_outputs()
    if not outputs:
        print("\n✗ Stack not deployed. Run ./deploy.sh first")
        return
    
    # Test DynamoDB
    table_name = outputs.get('SurveyTableName')
    if table_name:
        test_dynamodb_access(table_name)
    
    # Test Lambda
    lambda_name = outputs.get('SurveyLambdaArn', '').split(':')[-1]
    if lambda_name:
        test_lambda_function(lambda_name)
    
    # List Connect instances
    list_connect_instances()
    
    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)


if __name__ == '__main__':
    main()
