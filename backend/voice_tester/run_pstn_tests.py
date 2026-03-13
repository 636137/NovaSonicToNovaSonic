#!/usr/bin/env python3
"""
PSTN Voice Tester using Amazon Chime SDK

Makes real phone calls to Amazon Connect using the existing SIP Media Application
infrastructure. Uses Polly for TTS and Transcribe for STT during the call.

Architecture:
1. create_sip_media_application_call -> Makes outbound call to Connect
2. SIP Media App Lambda handles call events (CALL_ANSWERED, etc.)
3. Lambda uses Polly to generate speech, sends to callee
4. Lambda receives audio, transcribes with Amazon Transcribe
5. Nova Sonic/Claude generates intelligent responses

Prerequisites:
- SIP Media Application: treasury-synthetic-caller
- Lambda: treasury-sip-media-app
- Phone: +13602098836 (for caller ID)
"""
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

import boto3
import yaml


@dataclass
class PSTNTestConfig:
    """Configuration for PSTN voice testing."""
    # Chime SDK resources
    sip_media_app_id: str = "3998e0ab-53e5-4f68-a2fd-1745f73e7aa1"
    from_phone: str = "+13602098836"
    
    # Target Connect number
    to_phone: str = ""
    
    # Test settings
    timeout_seconds: int = 180
    region: str = "us-east-1"
    
    # AI settings
    use_nova_sonic: bool = True
    bedrock_model: str = "anthropic.claude-3-sonnet-20240229-v1:0"


@dataclass
class CallResult:
    """Result of a PSTN test call."""
    test_id: str
    transaction_id: str = ""
    status: str = "pending"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: float = 0
    transcript: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class PSTNVoiceTester:
    """Makes real phone calls to test Amazon Connect flows."""
    
    def __init__(self, config: PSTNTestConfig):
        self.config = config
        self.chime = boto3.client('chime-sdk-voice', region_name=config.region)
        self.lambda_client = boto3.client('lambda', region_name=config.region)
        self.dynamodb = boto3.resource('dynamodb', region_name=config.region)
        
    def start_call(self, scenario: Dict[str, Any]) -> CallResult:
        """
        Start a PSTN call to the target number.
        
        The call is handled by the SIP Media Application Lambda which:
        1. Receives CALL_ANSWERED event
        2. Plays prompts using Polly
        3. Listens for responses
        4. Uses AI to generate contextual responses
        """
        test_id = f"pstn-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        
        result = CallResult(
            test_id=test_id,
            started_at=datetime.now()
        )
        
        print(f"\n{'='*60}")
        print(f"PSTN Voice Test: {test_id}")
        print(f"{'='*60}")
        print(f"From: {self.config.from_phone}")
        print(f"To: {self.config.to_phone}")
        print(f"SIP App: {self.config.sip_media_app_id}")
        
        try:
            # Store scenario in DynamoDB for Lambda to access
            self._store_test_scenario(test_id, scenario)
            
            # Make the call
            print("\n📞 Initiating PSTN call...")
            response = self.chime.create_sip_media_application_call(
                FromPhoneNumber=self.config.from_phone,
                ToPhoneNumber=self.config.to_phone,
                SipMediaApplicationId=self.config.sip_media_app_id,
                ArgumentsMap={
                    'test_id': test_id,
                    'scenario_name': scenario.get('name', 'Unknown'),
                    'mode': 'voice_test'
                }
            )
            
            result.transaction_id = response.get('SipMediaApplicationCall', {}).get('TransactionId', '')
            result.status = "dialing"
            
            print(f"✅ Call initiated!")
            print(f"   Transaction ID: {result.transaction_id}")
            
            # Wait for call to complete or timeout
            print(f"\n⏳ Waiting for call (timeout: {self.config.timeout_seconds}s)...")
            result = self._wait_for_call_completion(result)
            
        except Exception as e:
            result.status = "failed"
            result.errors.append(str(e))
            print(f"❌ Call failed: {e}")
        
        result.ended_at = datetime.now()
        if result.started_at:
            result.duration_seconds = (result.ended_at - result.started_at).total_seconds()
        
        return result
    
    def _store_test_scenario(self, test_id: str, scenario: Dict[str, Any]):
        """Store test scenario in DynamoDB for Lambda to access."""
        try:
            table = self.dynamodb.Table('voice-test-scenarios')
            table.put_item(Item={
                'test_id': test_id,
                'scenario': json.dumps(scenario),
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'transcript': []
            })
            print(f"📝 Scenario stored in DynamoDB")
        except Exception as e:
            print(f"⚠️  Could not store scenario: {e}")
    
    def _wait_for_call_completion(self, result: CallResult) -> CallResult:
        """Poll for call completion using transaction_id (what Lambda uses)."""
        start_time = time.time()
        
        # Lambda uses transaction_id as the test_id
        poll_id = result.transaction_id if result.transaction_id else result.test_id
        
        while time.time() - start_time < self.config.timeout_seconds:
            try:
                table = self.dynamodb.Table('voice-test-scenarios')
                response = table.get_item(Key={'test_id': poll_id})
                item = response.get('Item', {})
                
                status = item.get('status', 'pending')
                if status in ('completed', 'failed', 'hangup', 'received_input'):
                    result.status = status
                    result.transcript = item.get('transcript', '[]')
                    if isinstance(result.transcript, str):
                        try:
                            result.transcript = json.loads(result.transcript)
                        except:
                            result.transcript = [result.transcript]
                    print(f"\n📱 Call ended: {status}")
                    return result
                    
            except Exception as e:
                print(f"   Poll error: {e}")
            
            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0:
                print(f"   ... {elapsed}s elapsed")
            
            time.sleep(2)
        
        result.status = "timeout"
        print(f"\n⏰ Call timed out after {self.config.timeout_seconds}s")
        return result


def run_pstn_tests():
    """Run PSTN voice tests against Connect instances."""
    
    print("="*60)
    print("Amazon Connect PSTN Voice Tests")
    print("="*60)
    print("Using Chime SDK SIP Media Application")
    print()
    
    # Define targets
    targets = [
        {
            "name": "Census Survey",
            "phone": "+18332895330",
            "scenario": {
                "name": "Census Survey Test",
                "persona": "Cooperative survey participant",
                "steps": [
                    {"action": "listen", "expect": ["census", "survey"]},
                    {"action": "speak", "text": "Yes, I would like to participate"},
                    {"action": "listen", "expect": ["language", "english"]},
                    {"action": "speak", "text": "English"},
                ]
            }
        },
        {
            "name": "Treasury IVR",
            "phone": "+18332896602",
            "scenario": {
                "name": "Treasury IVR Test",
                "persona": "Treasury caller seeking IRS info",
                "steps": [
                    {"action": "listen", "expect": ["treasury", "press"]},
                    {"action": "dtmf", "digits": "1"},
                    {"action": "listen", "expect": ["irs", "tax"]},
                ]
            }
        }
    ]
    
    results = []
    
    for target in targets:
        print(f"\n{'='*60}")
        print(f"Testing: {target['name']}")
        print(f"{'='*60}")
        
        config = PSTNTestConfig(
            to_phone=target["phone"],
            timeout_seconds=120
        )
        
        tester = PSTNVoiceTester(config)
        result = tester.start_call(target["scenario"])
        
        results.append({
            "target": target["name"],
            "phone": target["phone"],
            "test_id": result.test_id,
            "transaction_id": result.transaction_id,
            "status": result.status,
            "duration": result.duration_seconds,
            "errors": result.errors
        })
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    success_statuses = ("completed", "received_input", "hangup")
    
    for r in results:
        status_icon = "✅" if r["status"] in success_statuses else "⏰" if r["status"] == "timeout" else "❌"
        print(f"{status_icon} {r['target']}: {r['status']} ({r['duration']:.1f}s)")
        if r["errors"]:
            for e in r["errors"]:
                print(f"   Error: {e}")
    
    # Save results
    output_path = Path(__file__).parent.parent / "voice_output" / "pstn_results.json"
    output_path.parent.mkdir(exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump({
            "run_at": datetime.now().isoformat(),
            "results": results
        }, f, indent=2)
    
    print(f"\n📁 Results saved to: {output_path}")
    
    return all(r["status"] in success_statuses for r in results)


if __name__ == "__main__":
    success = run_pstn_tests()
    sys.exit(0 if success else 1)
