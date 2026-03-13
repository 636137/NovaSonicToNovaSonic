#!/usr/bin/env python3
"""
Nova Sonic Deployment Script
Automates environment setup and validates everything is working.

Usage:
    python deploy_nova_sonic.py [--check-only] [--run-demo]
"""

import subprocess
import sys
import os
import shutil

def run(cmd, check=True, capture=False):
    """Run a command and return result."""
    print(f"  → {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    if check and result.returncode != 0:
        if capture:
            print(f"    Error: {result.stderr}")
        return None
    return result.stdout if capture else True

def check_python_version():
    """Check Python version is 3.12+."""
    print("\n📋 Checking Python version...")
    version = sys.version_info
    if version.major == 3 and version.minor >= 12:
        print(f"  ✅ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"  ❌ Python {version.major}.{version.minor} - Need 3.12+")
        return False

def check_aws_credentials():
    """Check AWS credentials are configured."""
    print("\n📋 Checking AWS credentials...")
    result = run("aws sts get-caller-identity --output text", capture=True)
    if result:
        print(f"  ✅ AWS credentials valid")
        return True
    else:
        print("  ❌ AWS credentials not configured")
        print("     Run: aws configure")
        return False

def check_bedrock_access():
    """Check Nova Sonic model access."""
    print("\n📋 Checking Bedrock model access...")
    try:
        import boto3
        bedrock = boto3.client('bedrock', region_name='us-east-1')
        response = bedrock.get_foundation_model(modelIdentifier='amazon.nova-sonic-v1:0')
        status = response['modelDetails']['modelLifecycle']['status']
        print(f"  ✅ Nova Sonic model status: {status}")
        return True
    except Exception as e:
        if "AccessDeniedException" in str(e):
            print("  ❌ Nova Sonic not enabled in Bedrock console")
            print("     Visit: https://console.aws.amazon.com/bedrock/")
        else:
            print(f"  ❌ Error: {e}")
        return False

def check_dependencies():
    """Check required packages are installed."""
    print("\n📋 Checking dependencies...")
    packages = {
        'boto3': 'boto3',
        'sounddevice': 'sounddevice',
        'numpy': 'numpy',
        'aws_sdk_bedrock_runtime': 'aws-sdk-bedrock-runtime'
    }
    missing = []
    for module, package in packages.items():
        try:
            __import__(module)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package} - not installed")
            missing.append(package)
    return missing

def install_dependencies(missing):
    """Install missing packages."""
    print("\n📦 Installing missing packages...")
    for package in missing:
        run(f"pip install {package}")

def create_venv():
    """Create Python 3.12 virtual environment if needed."""
    print("\n🔧 Setting up virtual environment...")
    
    if os.path.exists('.venv312'):
        print("  ✅ .venv312 already exists")
        return True
    
    # Try to create with python3.12
    result = run("python3.12 -m venv .venv312", check=False)
    if result:
        print("  ✅ Created .venv312")
        print("  ⚠️  Activate with: source .venv312/bin/activate")
        return True
    else:
        print("  ❌ Python 3.12 not found")
        print("     Install with: brew install python@3.12")
        print("     Or use pyenv: pyenv install 3.12.8")
        return False

def run_test():
    """Run a quick test to verify everything works."""
    print("\n🧪 Running quick test...")
    
    test_code = '''
import asyncio
import os
import boto3

# Setup credentials
session = boto3.Session()
creds = session.get_credentials()
os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key
os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
if creds.token:
    os.environ["AWS_SESSION_TOKEN"] = creds.token

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

async def test():
    config = Config(
        endpoint_uri="https://bedrock-runtime.us-east-1.amazonaws.com",
        region="us-east-1",
        aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)
    stream = await client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id="amazon.nova-sonic-v1:0")
    )
    print("  ✅ Successfully connected to Nova Sonic!")
    return True

asyncio.run(test())
'''
    
    result = subprocess.run([sys.executable, '-c', test_code], capture_output=True, text=True)
    if result.returncode == 0:
        print(result.stdout)
        return True
    else:
        print(f"  ❌ Test failed: {result.stderr}")
        return False

def main():
    print("=" * 60)
    print("🚀 NOVA SONIC DEPLOYMENT")
    print("=" * 60)
    
    check_only = '--check-only' in sys.argv
    run_demo = '--run-demo' in sys.argv
    
    # Check prerequisites
    py_ok = check_python_version()
    aws_ok = check_aws_credentials()
    bedrock_ok = check_bedrock_access() if aws_ok else False
    missing = check_dependencies()
    
    if check_only:
        print("\n" + "=" * 60)
        if py_ok and aws_ok and bedrock_ok and not missing:
            print("✅ All checks passed!")
        else:
            print("❌ Some checks failed - see above")
        return
    
    # Auto-fix what we can
    if missing:
        install_dependencies(missing)
        missing = check_dependencies()
    
    if not py_ok:
        create_venv()
        print("\n⚠️  Please activate venv and re-run:")
        print("    source .venv312/bin/activate")
        print("    python deploy_nova_sonic.py")
        return
    
    # Run test
    if py_ok and aws_ok and bedrock_ok and not missing:
        test_ok = run_test()
        
        print("\n" + "=" * 60)
        if test_ok:
            print("✅ DEPLOYMENT SUCCESSFUL!")
            print("\nNext steps:")
            print("  python voice_tester/sonic_live_playback.py")
            
            if run_demo:
                print("\n🎬 Running demo...")
                os.system("python voice_tester/sonic_live_playback.py")
        else:
            print("❌ Test failed - check errors above")
    else:
        print("\n" + "=" * 60)
        print("❌ Prerequisites not met")
        print("\nFix the issues above and re-run this script")

if __name__ == "__main__":
    main()
