#!/usr/bin/env python3
"""Fix IAM role permissions for Lex voice."""
import boto3
import json

iam = boto3.client('iam')
role_name = 'TreasuryAgentCoreStack-AgentCoreExecutionRole416A5D-jqjeRyIq8z7U'

# Create a policy for Lex voice capabilities
policy_document = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "polly:SynthesizeSpeech",
                "polly:DescribeVoices"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "lex:*"
            ],
            "Resource": "*"
        }
    ]
}

# Create or update the policy
policy_name = "LexVoicePermissions"

try:
    # Try to create the policy
    response = iam.create_policy(
        PolicyName=policy_name,
        PolicyDocument=json.dumps(policy_document),
        Description="Permissions for Lex voice synthesis"
    )
    policy_arn = response['Policy']['Arn']
    print(f"Created policy: {policy_arn}")
except iam.exceptions.EntityAlreadyExistsException:
    # Policy already exists, get its ARN
    account_id = boto3.client('sts').get_caller_identity()['Account']
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
    print(f"Policy exists: {policy_arn}")

# Attach policy to role
try:
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn=policy_arn
    )
    print(f"Attached {policy_name} to {role_name}")
except Exception as e:
    print(f"Error attaching policy: {e}")

# Also attach managed Polly policy
try:
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn='arn:aws:iam::aws:policy/AmazonPollyFullAccess'
    )
    print("Attached AmazonPollyFullAccess")
except Exception as e:
    print(f"Note: {e}")

print("\nListing attached policies:")
policies = iam.list_attached_role_policies(RoleName=role_name)
for p in policies['AttachedPolicies']:
    print(f"  - {p['PolicyName']}")
