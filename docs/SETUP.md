# Amazon Connect Census Survey - Setup Guide

## Prerequisites

Before deploying the Census Survey system, ensure you have:

1. **AWS Account** with appropriate permissions
2. **AWS CLI** installed and configured
3. **Python 3.9+** installed
4. **Node.js 16+** installed (for AWS CDK)
5. **AWS CDK CLI** installed globally

## Step-by-Step Setup

### 1. Configure AWS Credentials

Your AWS credentials are already configured in the `.env` file. To use them:

```bash
export $(cat .env | grep -v '^#' | xargs)
```

Verify credentials:
```bash
aws sts get-caller-identity
```

### 2. Install Dependencies

Install Python packages:
```bash
pip install -r requirements.txt
```

Install AWS CDK globally (if not already installed):
```bash
npm install -g aws-cdk
```

### 3. Bootstrap CDK

Run this once per AWS account/region combination:
```bash
cdk bootstrap
```

### 4. Deploy Infrastructure

Run the automated deployment script:
```bash
chmod +x deploy.sh
./deploy.sh
```

Or deploy manually:

```bash
# Deploy CDK stack
cdk deploy

# Create Connect instance and configure
chmod +x scripts/create_connect_instance.py
python3 scripts/create_connect_instance.py
```

### 5. Configure Phone Number (Voice Calls)

1. Go to AWS Console → Amazon Connect
2. Navigate to your Connect instance
3. Go to **Channels** → **Phone numbers**
4. **Claim a number** or port an existing number
5. Associate the number with the **Voice Survey Flow**

### 6. Enable Chat Widget

1. In Amazon Connect console, go to your instance
2. Navigate to **Channels** → **Chat widgets**
3. Create a new widget:
   - Name: Census Survey Chat
   - Contact flow: Chat Survey Flow
4. Copy the widget code and embed it in your website

### 7. Test the System

Run the test script:
```bash
chmod +x scripts/test_system.py
python3 scripts/test_system.py
```

Test manually:
- **Voice**: Call the phone number you configured
- **Chat**: Open the chat widget on your website

## Survey Flow

The AI agent will ask the following questions:

1. **Household Size**: How many people live in your household?
2. **Primary Language**: What is the primary language spoken?
3. **Employment Status**: Employed, unemployed, retired, or student?
4. **Age Range**: Under 18, 18-34, 35-54, 55-64, or 65+?
5. **Housing Type**: House, apartment, condo, or other?

All responses are stored in DynamoDB for analysis.

## Accessing Survey Data

### Via AWS Console

1. Go to AWS Console → DynamoDB
2. Find the `CensusSurveyResponses` table
3. Click **Explore table items**

### Via Python

```python
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('YOUR_TABLE_NAME')

response = table.scan()
for item in response['Items']:
    print(item)
```

## Monitoring

### CloudWatch Logs

- Lambda function logs: `/aws/lambda/ConnectCensusStack-*`
- Connect logs: Enabled in Connect instance settings

### Metrics

Go to CloudWatch → Dashboards to view:
- Number of surveys completed
- Average survey duration
- Contact flow success rate

## Troubleshooting

### "Access Denied" errors

Ensure your IAM user/role has the following permissions:
- Amazon Connect full access
- Lambda full access
- Lex V2 full access
- DynamoDB full access
- S3 access
- CloudFormation access

### Lex bot not responding

1. Check Lambda function logs in CloudWatch
2. Verify Lex bot is built and active
3. Ensure Lambda has permission to be invoked by Lex

### Contact flow errors

1. Verify Lambda ARN is correctly set in contact flow
2. Check Lambda execution role has DynamoDB permissions
3. Review Connect instance logs

## Cleanup

To delete all resources:

```bash
chmod +x scripts/cleanup.py
python3 scripts/cleanup.py
```

**Note**: DynamoDB table and S3 bucket are retained by default to prevent data loss.

## Cost Estimation

Approximate monthly costs (for 1000 surveys):

- Amazon Connect: ~$100 (voice) or ~$50 (chat only)
- Amazon Lex: ~$5-10
- Lambda: ~$1-2
- DynamoDB: ~$1-5
- S3: <$1

Total: ~$110-120/month for voice + chat

## Support

For issues or questions:
1. Check CloudWatch logs for errors
2. Review AWS documentation
3. Contact AWS Support

## Next Steps

1. Customize survey questions in Lex bot definition
2. Add data analytics dashboard
3. Integrate with your CRM or data warehouse
4. Set up automated reports
5. Configure alerts for survey completion rates
