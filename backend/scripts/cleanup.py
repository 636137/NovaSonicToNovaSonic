#!/usr/bin/env python3
"""
Script to delete all Census Survey resources
WARNING: This will delete the Connect instance, Lex bot, and all data!
"""
import boto3
import sys

connect_client = boto3.client('connect')
cfn_client = boto3.client('cloudformation')


def confirm_deletion():
    """Confirm user wants to delete everything"""
    print("=" * 60)
    print("WARNING: This will DELETE all Census Survey resources!")
    print("=" * 60)
    print("\nThis includes:")
    print("  - Amazon Connect instance")
    print("  - Lex bot")
    print("  - Lambda functions")
    print("  - DynamoDB table (data will be retained due to RETAIN policy)")
    print("  - S3 bucket (data will be retained)")
    print()
    
    response = input("Are you sure you want to continue? (type 'DELETE' to confirm): ")
    
    return response == 'DELETE'


def delete_connect_instance():
    """Delete Connect instance"""
    print("\nDeleting Connect instances...")
    
    try:
        instances = connect_client.list_instances()
        
        for instance in instances['InstanceSummaryList']:
            if 'Census' in instance['InstanceAlias']:
                print(f"Deleting instance: {instance['InstanceAlias']}")
                connect_client.delete_instance(InstanceId=instance['Id'])
                print(f"✓ Deleted: {instance['Id']}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error deleting instances: {str(e)}")
        return False


def delete_cdk_stack():
    """Delete CDK stack"""
    print("\nDeleting CDK stack...")
    
    try:
        cfn_client.delete_stack(StackName='ConnectCensusStack')
        print("✓ Stack deletion initiated")
        print("  (This may take several minutes)")
        
        return True
        
    except Exception as e:
        print(f"✗ Error deleting stack: {str(e)}")
        return False


def main():
    """Main execution"""
    if not confirm_deletion():
        print("\nDeletion cancelled.")
        sys.exit(0)
    
    print("\nProceeding with deletion...")
    
    # Delete Connect instance first
    delete_connect_instance()
    
    # Delete CDK stack
    delete_cdk_stack()
    
    print("\n" + "=" * 60)
    print("Cleanup Complete")
    print("=" * 60)
    print("\nNote: DynamoDB table and S3 bucket are retained to prevent")
    print("accidental data loss. Delete them manually if needed.")


if __name__ == '__main__':
    main()
