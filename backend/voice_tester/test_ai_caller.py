#!/usr/bin/env python3
"""
Test script for AI Caller Client

Tests the integration of:
- Amazon Bedrock (Claude) for response generation
- Amazon Polly for text-to-speech
"""
import asyncio
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice_tester.ai_caller_client import AICallerClient, AICallerConfig


async def test_ai_caller():
    """Run comprehensive tests on AI Caller"""
    
    print("=" * 60)
    print("AI Caller Integration Tests")
    print("=" * 60)
    
    errors = []
    
    # Test 1: Create client
    print("\n[Test 1] Creating AI Caller client...")
    try:
        config = AICallerConfig(
            region='us-east-1',
            polly_voice_id='Joanna',
            llm_model_id='anthropic.claude-3-sonnet-20240229-v1:0'
        )
        client = AICallerClient(config)
        print("  ✓ Client created successfully")
    except Exception as e:
        errors.append(f"Test 1 failed: {e}")
        print(f"  ✗ Failed: {e}")
        return errors
    
    # Test 2: Set persona
    print("\n[Test 2] Setting persona...")
    try:
        persona = {
            'name': 'Maria Garcia',
            'background': 'A 38-year-old professional calling about census',
            'attributes': {
                'voice_type': 'female_professional',
                'speaking_rate': 'normal',
                'patience': 'high'
            }
        }
        client.set_persona(persona)
        print("  ✓ Persona set successfully")
        print(f"    Voice: {client.config.polly_voice_id}")
    except Exception as e:
        errors.append(f"Test 2 failed: {e}")
        print(f"  ✗ Failed: {e}")
    
    # Test 3: Generate response using Bedrock
    print("\n[Test 3] Generating response with Bedrock Claude...")
    try:
        response = await client.generate_response(
            agent_message="Welcome to the census survey. Would you like to take it in English or Spanish?",
            intent="Say you want English"
        )
        print("  ✓ Response generated successfully")
        print(f"    Response: {response[:100]}..." if len(response) > 100 else f"    Response: {response}")
    except Exception as e:
        errors.append(f"Test 3 failed: {e}")
        print(f"  ✗ Failed: {e}")
    
    # Test 4: Synthesize speech using Polly
    print("\n[Test 4] Synthesizing speech with Polly...")
    try:
        text = "Hello, I would like to take the survey in English please."
        audio = await client.synthesize_speech(text)
        print("  ✓ Speech synthesized successfully")
        print(f"    Audio size: {len(audio)} bytes")
        print(f"    Duration estimate: ~{len(audio) / 32000:.1f} seconds")
    except Exception as e:
        errors.append(f"Test 4 failed: {e}")
        print(f"  ✗ Failed: {e}")
    
    # Test 5: Full turn processing
    print("\n[Test 5] Processing full conversation turn...")
    try:
        response_text, response_audio = await client.respond_to_prompt(
            prompt="Are you currently employed?",
            intent="Answer yes and mention you own a small business"
        )
        print("  ✓ Full turn processed successfully")
        print(f"    Text: {response_text[:80]}..." if len(response_text) > 80 else f"    Text: {response_text}")
        print(f"    Audio: {len(response_audio)} bytes")
    except Exception as e:
        errors.append(f"Test 5 failed: {e}")
        print(f"  ✗ Failed: {e}")
    
    # Test 6: Conversation history
    print("\n[Test 6] Checking conversation history...")
    try:
        summary = client.get_conversation_summary()
        print("  ✓ Conversation summary retrieved")
        print(f"    Session ID: {summary['session_id'][:8]}...")
        print(f"    Turn count: {summary['turn_count']}")
    except Exception as e:
        errors.append(f"Test 6 failed: {e}")
        print(f"  ✗ Failed: {e}")
    
    # Test 7: Different voices
    print("\n[Test 7] Testing different Polly voices...")
    voices_to_test = ['Matthew', 'Salli', 'Joey']
    for voice in voices_to_test:
        try:
            client.config.polly_voice_id = voice
            audio = await client.synthesize_speech("Testing voice.")
            print(f"  ✓ {voice}: {len(audio)} bytes")
        except Exception as e:
            errors.append(f"Test 7 ({voice}) failed: {e}")
            print(f"  ✗ {voice} failed: {e}")
    
    # Test 8: Reset conversation
    print("\n[Test 8] Testing conversation reset...")
    try:
        old_session = client.session_id
        client.reset_conversation()
        new_session = client.session_id
        assert old_session != new_session, "Session ID should change after reset"
        assert len(client.conversation_history) == 0, "History should be empty"
        print("  ✓ Conversation reset successfully")
    except Exception as e:
        errors.append(f"Test 8 failed: {e}")
        print(f"  ✗ Failed: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"TESTS COMPLETED WITH {len(errors)} ERROR(S)")
        for error in errors:
            print(f"  - {error}")
        return errors
    else:
        print("ALL TESTS PASSED! ✓")
        return []


async def test_polly_only():
    """Quick test of Polly TTS only (no Bedrock)"""
    
    print("\n" + "=" * 60)
    print("Polly-Only Mode Test")
    print("=" * 60)
    
    try:
        config = AICallerConfig(
            region='us-east-1',
            polly_voice_id='Joanna'
        )
        client = AICallerClient(config)
        
        # Just test TTS
        audio = await client.synthesize_speech(
            "This is a test of the Polly text to speech system."
        )
        print(f"  ✓ Polly synthesis successful: {len(audio)} bytes")
        return True
        
    except Exception as e:
        print(f"  ✗ Polly test failed: {e}")
        return False


if __name__ == "__main__":
    print("\nStarting AI Caller Tests...\n")
    
    # Run main tests
    errors = asyncio.run(test_ai_caller())
    
    # Run polly-only test
    asyncio.run(test_polly_only())
    
    # Exit with appropriate code
    sys.exit(1 if errors else 0)
