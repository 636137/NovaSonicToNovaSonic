#!/bin/bash

# Installation script for Amazon Connect Census Survey
# This installs all prerequisites needed for deployment

echo "=========================================="
echo "Amazon Connect Census Survey"
echo "Prerequisite Installation"
echo "=========================================="
echo ""

# Detect OS
OS="$(uname -s)"
case "${OS}" in
    Darwin*)    PLATFORM=macos;;
    Linux*)     PLATFORM=linux;;
    *)          PLATFORM="unknown"
esac

echo "Detected platform: ${PLATFORM}"
echo ""

# Check Python
echo "Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo "✓ Python ${PYTHON_VERSION} installed"
else
    echo "✗ Python 3 not found"
    echo "  Please install Python 3.9 or later from https://www.python.org/"
    exit 1
fi

# Check pip
echo ""
echo "Checking pip..."
if command -v pip3 &> /dev/null; then
    echo "✓ pip3 installed"
else
    echo "✗ pip3 not found"
    echo "  Installing pip3..."
    python3 -m ensurepip --default-pip
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -q boto3 aws-cdk-lib constructs python-dotenv
echo "✓ Python dependencies installed"

# Check Node.js
echo ""
echo "Checking Node.js..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    echo "✓ Node.js ${NODE_VERSION} installed"
else
    echo "✗ Node.js not found"
    
    if [ "$PLATFORM" = "macos" ]; then
        echo ""
        echo "Installing Node.js using Homebrew..."
        if command -v brew &> /dev/null; then
            brew install node
        else
            echo "  Homebrew not found. Please install from https://nodejs.org/"
            exit 1
        fi
    else
        echo "  Please install Node.js 16+ from https://nodejs.org/"
        exit 1
    fi
fi

# Check npm
echo ""
echo "Checking npm..."
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    echo "✓ npm ${NPM_VERSION} installed"
else
    echo "✗ npm not found (should come with Node.js)"
    exit 1
fi

# Install AWS CDK
echo ""
echo "Installing AWS CDK..."
if command -v cdk &> /dev/null; then
    CDK_VERSION=$(cdk --version)
    echo "✓ AWS CDK already installed: ${CDK_VERSION}"
else
    npm install -g aws-cdk
    echo "✓ AWS CDK installed"
fi

# Check AWS CLI
echo ""
echo "Checking AWS CLI..."
if command -v aws &> /dev/null; then
    AWS_VERSION=$(aws --version)
    echo "✓ AWS CLI installed: ${AWS_VERSION}"
else
    echo "⚠ AWS CLI not found"
    echo "  Installing AWS CLI..."
    
    if [ "$PLATFORM" = "macos" ]; then
        if command -v brew &> /dev/null; then
            brew install awscli
            echo "✓ AWS CLI installed via Homebrew"
        else
            pip3 install awscli
            echo "✓ AWS CLI installed via pip"
        fi
    else
        pip3 install awscli
        echo "✓ AWS CLI installed via pip"
    fi
fi

# Verify AWS credentials
echo ""
echo "Checking AWS credentials..."
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo "✓ Credentials loaded from .env"
    
    # Test credentials
    python3 -c "import boto3; sts = boto3.client('sts'); info = sts.get_caller_identity(); print(f\"✓ AWS Account: {info['Account']}\"); print(f\"✓ User: {info['Arn'].split('/')[-1]}\")" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo "✓ AWS credentials are valid"
    else
        echo "⚠ Could not verify AWS credentials"
    fi
else
    echo "⚠ .env file not found"
    echo "  Please create .env with your AWS credentials"
fi

# Summary
echo ""
echo "=========================================="
echo "Installation Summary"
echo "=========================================="
echo "✓ Python installed and configured"
echo "✓ Node.js and npm installed"
echo "✓ AWS CDK installed"
echo "✓ AWS CLI installed"
echo "✓ Python dependencies installed"
echo ""
echo "Next steps:"
echo "1. Ensure .env file has your AWS credentials"
echo "2. Run: ./deploy.sh"
echo ""
echo "For detailed instructions, see QUICKSTART.md"
echo "=========================================="
