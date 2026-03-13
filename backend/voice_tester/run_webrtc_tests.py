#!/usr/bin/env python3
"""
Run WebRTC voice tests against Amazon Connect instances.

Uses WebRTC protocol (no phone number needed) to test contact flows directly.
"""
import asyncio
import json
import os
import sys
import yaml
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from voice_tester.webrtc_tester import AmazonConnectWebRTCTester, WebRTCConfig


# Instance configurations
INSTANCES = {
    "census-enumerator-9652": {
        "instance_id": "1d3555df-0f7a-4c78-9177-d42253597de2",
        "flows": {
            "Census Survey Flow": "4ed0dc27-6319-47e6-b98d-71cac718e656",
            "Census AI Agent": "4a2354b7-b179-400d-b175-82051ff9059d",
        }
    },
    "treasury-connect-prod": {
        "instance_id": "a88ddab9-3b29-409f-87f0-bdb614abafef",
        "flows": {
            "TreasuryConversationalFlow": "8dfd7f4a-e383-4889-a941-d516d4919a50",
            "TreasuryAgentCoreFlow": "27e3aaec-09ca-40d1-8101-90b1b921712e",
        }
    }
}


async def run_webrtc_test(instance_name: str, flow_name: str, scenario: dict) -> dict:
    """Run a single WebRTC test against a contact flow."""
    
    instance = INSTANCES.get(instance_name)
    if not instance:
        return {"error": f"Unknown instance: {instance_name}"}
    
    flow_id = instance["flows"].get(flow_name)
    if not flow_id:
        return {"error": f"Unknown flow: {flow_name}"}
    
    print(f"\n{'='*60}")
    print(f"WebRTC Test: {flow_name}")
    print(f"Instance: {instance_name}")
    print(f"Flow ID: {flow_id}")
    print(f"{'='*60}")
    
    config = WebRTCConfig(
        connect_instance_id=instance["instance_id"],
        contact_flow_id=flow_id,
        region="us-east-1",
    )
    
    tester = AmazonConnectWebRTCTester(config)
    
    result = {
        "test_name": f"{instance_name}/{flow_name}",
        "started_at": datetime.now().isoformat(),
        "status": "starting",
    }
    
    try:
        print("📞 Initiating WebRTC connection...")
        call_state = await tester.start_test_call(
            scenario=scenario,
            test_id=f"webrtc-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        
        result["status"] = call_state.status
        result["contact_id"] = call_state.contact_id
        result["conversation"] = call_state.conversation
        result["completed_at"] = datetime.now().isoformat()
        
        print(f"✅ Test completed: {call_state.status}")
        print(f"   Contact ID: {call_state.contact_id}")
        print(f"   Steps: {len(call_state.conversation)}")
        
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        print(f"❌ Test failed: {e}")
    
    return result


async def main():
    print("="*60)
    print("Amazon Connect WebRTC Voice Tests")
    print("="*60)
    
    # Load census survey scenario
    scenario_path = Path(__file__).parent / "scenarios" / "census_survey_webrtc.yaml"
    
    if scenario_path.exists():
        with open(scenario_path) as f:
            scenario = yaml.safe_load(f)
        print(f"Loaded scenario: {scenario.get('name', 'Unknown')}")
    else:
        # Default minimal scenario
        scenario = {
            "name": "WebRTC Quick Test",
            "steps": [
                {"id": "listen", "action": "listen", "expect": {"timeout_seconds": 10}},
                {"id": "respond", "action": "speak", "content": {"text": "Hello"}}
            ]
        }
    
    results = []
    
    # Test Census Survey Flow
    result = await run_webrtc_test(
        "census-enumerator-9652",
        "Census Survey Flow",
        scenario
    )
    results.append(result)
    
    # Save results
    output_path = Path(__file__).parent.parent / "voice_output" / "webrtc_results.json"
    output_path.parent.mkdir(exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump({
            "run_at": datetime.now().isoformat(),
            "results": results
        }, f, indent=2)
    
    print(f"\n📁 Results saved to: {output_path}")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results if r.get("status") not in ("failed", "error"))
    failed = len(results) - passed
    
    print(f"Total: {len(results)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
