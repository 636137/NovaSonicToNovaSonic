# Quick Start Guide - Amazon Connect Census Survey

## Installation & Deployment

### Prerequisites Check

Your AWS credentials are configured and working! ✓
- Account: 593804350786
- User: ChadDHendren@maximus.com
- Region: us-east-1

### Step 1: Install Required Tools

#### Install AWS CLI (if not already installed)

On macOS:
```bash
# Using Homebrew
brew install awscli

# Or using pip
pip3 install awscli
```

Verify installation:
```bash
aws --version
```

#### Install Node.js and AWS CDK

```bash
# Install Node.js (if not already installed)
# Download from https://nodejs.org/ or use Homebrew:
brew install node

# Install AWS CDK
npm install -g aws-cdk

# Verify CDK installation
cdk --version
```

### Step 2: Install Python Dependencies

```bash
cd /Users/ChadDHendren/AmazonConnect1
pip3 install -r requirements.txt
```

### Step 3: Configure AWS Credentials

Your credentials are already in the `.env` file. To activate them:

```bash
export $(cat .env | grep -v '^#' | xargs)
```

Or configure AWS CLI permanently:
```bash
aws configure
# Enter your Access Key ID: <YOUR_AWS_ACCESS_KEY_ID>
# Enter your Secret Access Key: (your secret key)
# Default region: us-east-1
# Default output format: json
```

### Step 4: Bootstrap AWS CDK

Run this once (first time only):
```bash
cd /Users/ChadDHendren/AmazonConnect1
cdk bootstrap aws://593804350786/us-east-1
```

### Step 5: Deploy the Infrastructure

#### Option A: Automated Deployment (Recommended)

```bash
cd /Users/ChadDHendren/AmazonConnect1
./deploy.sh
```

This will:
1. Install dependencies
2. Deploy CDK stack (Lambda, DynamoDB, S3)
3. Create Amazon Connect instance
4. Create and configure Lex bot
5. Import contact flows

#### Option B: Manual Step-by-Step Deployment

```bash
cd /Users/ChadDHendren/AmazonConnect1

# 1. Deploy CDK infrastructure
cdk deploy

# 2. Create Connect instance and configure
python3 scripts/create_connect_instance.py

# 3. Test the deployment
python3 scripts/test_system.py
```

### Step 6: Configure Phone Number for Voice Calls

1. Open AWS Console: https://console.aws.amazon.com/connect/
2. Select your region: **us-east-1**
3. Click on your Connect instance (CensusSurvey)
4. Navigate to **Channels** → **Phone numbers**
5. Click **Claim a number**
6. Select a number and click **Save**
7. associate the number with **Voice Survey Flow**

### Step 7: Enable Chat Widget

1. In Connect console, go to **Channels** → **Chat**
2. Click **Add chat widget**
3. Configure:
   - Widget name: Census Survey Chat
   - Contact flow: Chat Survey Flow
4. Copy the embed code
5. Add it to your website where you want the chat to appear

## Testing the System

### Test Voice Survey

1. Call the phone number you claimed
2. Follow the AI agent's questions
3. Complete the survey

### Test Chat Survey

1. Open your website with the chat widget
2. Click the chat icon
3. Start the conversation with the AI agent
4. Answer the survey questions

### Verify Data Collection

Check DynamoDB for survey responses:

```bash
# Using AWS CLI
aws dynamodb scan --table-name <your-table-name> --region us-east-1

# Using Python
python3 scripts/test_system.py
```

## Project Structure

```
AmazonConnect1/
├── app.py                          # CDK app entry point
├── cdk.json                        # CDK configuration
├── requirements.txt                # Python dependencies
├── package.json                    # Node.js dependencies
├── deploy.sh                       # Automated deployment script
├── .env                           # AWS credentials (DO NOT COMMIT)
├── .gitignore                     # Git ignore rules
├── README.md                      # Project overview
├── SETUP.md                       # Detailed setup guide
├── QUICKSTART.md                  # This file
│
├── cdk/                           # CDK infrastructure code
│   ├── __init__.py
│   └── connect_stack.py           # Stack definition
│
├── lambda/                        # Lambda functions
│   ├── survey/
│   │   └── survey_handler.py     # Survey data processing
│   └── lex/
│       └── lex_handler.py         # Lex bot fulfillment
│
├── lex/                           # Lex bot configuration
│   └── bot_definition.json        # Bot intents and slots
│
├── contact_flows/                 # Connect contact flows
│   ├── voice_survey_flow.json    # Voice call flow
│   └── chat_survey_flow.json     # Chat flow
│
└── scripts/                       # Utility scripts
    ├── create_connect_instance.py # Instance creation
    ├── test_system.py             # System testing
    └── cleanup.py                 # Resource cleanup
```

## Survey Questions

The AI agent will ask:

1. **Household Size**: How many people live in your household?
2. **Primary Language**: What is the primary language spoken at home?
3. **Employment Status**: Are you employed, unemployed, retired, or a student?
4. **Age Range**: What is your age range?
   - Under 18
   - 18 to 34
   - 35 to 54
   - 55 to 64
   - 65 and over
5. **Housing Type**: What type of housing do you live in?
   - House
   - Apartment
   - Condo
   - Other

## Monitoring & Analytics

### View Survey Results

**AWS Console:**
1. Go to DynamoDB
2. Select your table (CensusSurveyResponses)
3. Click "Explore table items"

**Python Script:**
```python
import boto3
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('YOUR_TABLE_NAME')
response = table.scan()
for item in response['Items']:
    print(item)
```

### View Logs

**Lambda logs:**
```bash
aws logs tail /aws/lambda/ConnectCensusStack-CensusSurveyFunction --follow
```

**Connect logs:**
- CloudWatch Logs → /aws/connect/YourInstanceId

## Troubleshooting

### Issue: CDK deployment fails

**Solution:**
```bash
# Ensure CDK is bootstrapped
cdk bootstrap

# Check for existing resources
aws cloudformation describe-stacks --stack-name ConnectCensusStack
```

### Issue: Lex bot not responding

**Solutions:**
1. Verify bot is built: AWS Console → Lex → Your bot → Check status
2. Check Lambda permissions: Lambda → Permissions
3. View Lambda logs: CloudWatch Logs

### Issue: Contact flow errors

**Solutions:**
1. Verify Lambda ARN in contact flow
2. Check Connect instance has Lambda permissions
3. Review contact flow JSON for syntax errors

## Cost Estimate

For 1,000 surveys per month:

- **Amazon Connect**: ~$100/month (voice) or ~$50/month (chat only)
- **Amazon Lex**: ~$5-10/month
- **AWS Lambda**: ~$1-2/month
- **DynamoDB**: ~$1-5/month
- **S3 Storage**: <$1/month

**Total**: ~$110-120/month (voice + chat)

## Cleanup

To delete all resources:

```bash
cd /Users/ChadDHendren/AmazonConnect1
python3 scripts/cleanup.py
```

**Note**: DynamoDB table and S3 bucket are retained to prevent accidental data loss.

## Next Steps

1. ✅ Deploy infrastructure
2. ✅ Test voice and chat flows
3. 📊 Set up analytics dashboard
4. 🔔 Configure CloudWatch alarms
5. 📧 Set up email notifications for completed surveys
6. 🎨 Customize chat widget appearance
7. 🌐 Add multi-language support
8. 📱 Create mobile app integration

## Support & Documentation

- **AWS Connect Docs**: https://docs.aws.amazon.com/connect/
- **AWS Lex Docs**: https://docs.aws.amazon.com/lex/
- **AWS CDK Docs**: https://docs.aws.amazon.com/cdk/

## Security Best Practices

1. ✅ Credentials are in `.env` (gitignored)
2. ⚠️ Never commit `.env` to version control
3. ✅ DynamoDB encryption at rest enabled
4. ✅ S3 bucket encryption enabled
5. ✅ S3 bucket blocks public access
6. 🔒 Consider rotating AWS credentials regularly
7. 🔒 Use IAM roles instead of access keys for production

---

**Ready to deploy?** Run: `./deploy.sh`

For detailed information, see [SETUP.md](SETUP.md)
