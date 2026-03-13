#!/bin/bash

# Census Survey Deployment Script
set -e

echo "=================================="
echo "Census Survey Deployment"
echo "=================================="

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo "✓ Environment variables loaded"
else
    echo "✗ .env file not found"
    exit 1
fi

# Check AWS credentials
echo ""
echo "Checking AWS credentials..."
aws sts get-caller-identity > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ AWS credentials configured"
    aws sts get-caller-identity
else
    echo "✗ AWS credentials not configured"
    exit 1
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo "✓ Python dependencies installed"

# Bootstrap CDK (if needed)
echo ""
echo "Checking CDK bootstrap..."
cdk bootstrap
echo "✓ CDK bootstrap complete"

# Deploy CDK stack
echo ""
echo "Deploying CDK stack..."
cdk deploy --require-approval never
echo "✓ CDK stack deployed"

# Create Connect instance and configure
echo ""
echo "Creating Connect instance..."
python3 scripts/create_connect_instance.py

echo ""
echo "=================================="
echo "Deployment Complete!"
echo "=================================="
