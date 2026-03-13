"""
Voice Tester CLI

Command-line interface for running voice tests against Amazon Connect.

Usage:
    python -m voice_tester.cli test <scenario.yaml> [--target-number <number>]
    python -m voice_tester.cli status <test_id>
    python -m voice_tester.cli results <test_id> [--include-recording]
    python -m voice_tester.cli list [--scenario <name>] [--limit <n>]
    python -m voice_tester.cli cancel <test_id>
    python -m voice_tester.cli provision-number [--area-code <code>]
    python -m voice_tester.cli deploy
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import yaml
import boto3

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from voice_tester.config import Config, load_scenario, validate_scenario, get_config


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='AI Voice Testing Agent for Amazon Connect',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a test scenario
  python -m voice_tester.cli test scenarios/census_survey_happy_path.yaml
  
  # Run with custom target number
  python -m voice_tester.cli test scenarios/my_test.yaml --target-number +15551234567
  
  # Check test status
  python -m voice_tester.cli status abc123-test-id
  
  # Get test results with recording
  python -m voice_tester.cli results abc123-test-id --include-recording
  
  # List recent tests
  python -m voice_tester.cli list --limit 10
  
  # Deploy infrastructure
  python -m voice_tester.cli deploy
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Run a voice test scenario')
    test_parser.add_argument('scenario', help='Path to scenario YAML file')
    test_parser.add_argument('--target-number', '-t', help='Target phone number (for PSTN mode)')
    test_parser.add_argument('--test-id', help='Custom test ID')
    test_parser.add_argument('--wait', '-w', action='store_true', help='Wait for test to complete')
    test_parser.add_argument('--timeout', type=int, default=300, help='Wait timeout in seconds')
    test_parser.add_argument('--mode', '-m', choices=['pstn', 'webrtc'], default='webrtc',
                            help='Test mode: pstn (phone call) or webrtc (direct connect)')
    test_parser.add_argument('--instance-id', help='Amazon Connect instance ID (for webrtc mode)')
    test_parser.add_argument('--contact-flow-id', help='Amazon Connect contact flow ID (for webrtc mode)')
    test_parser.add_argument('--voice-engine', '-v', choices=['nova-sonic', 'ai-caller', 'polly-only'], 
                            default='nova-sonic',
                            help='Voice engine: nova-sonic (S2S), ai-caller (Transcribe+LLM+Polly), or polly-only (TTS only)')
    test_parser.add_argument('--voice', choices=['matthew', 'tiffany', 'amy', 'Joanna', 'Matthew', 'Salli', 'Joey', 'Ruth', 'Stephen'], 
                            default='matthew',
                            help='Voice ID for speech synthesis')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Check test status')
    status_parser.add_argument('test_id', help='Test ID to check')
    
    # Results command
    results_parser = subparsers.add_parser('results', help='Get test results')
    results_parser.add_argument('test_id', help='Test ID to get results for')
    results_parser.add_argument('--include-recording', '-r', action='store_true', help='Include recording URLs')
    results_parser.add_argument('--output', '-o', help='Output file (JSON)')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List tests')
    list_parser.add_argument('--scenario', '-s', help='Filter by scenario name')
    list_parser.add_argument('--limit', '-l', type=int, default=20, help='Number of tests to list')
    
    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel a running test')
    cancel_parser.add_argument('test_id', help='Test ID to cancel')
    
    # Provision number command
    provision_parser = subparsers.add_parser('provision-number', help='Provision a phone number')
    provision_parser.add_argument('--area-code', '-a', help='Preferred area code')
    provision_parser.add_argument('--country', '-c', default='US', help='Country code')
    
    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy infrastructure via CDK')
    deploy_parser.add_argument('--destroy', action='store_true', help='Destroy the stack')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate a scenario file')
    validate_parser.add_argument('scenario', help='Path to scenario YAML file')
    
    # List Connect instances command
    instances_parser = subparsers.add_parser('list-instances', help='List Amazon Connect instances')
    
    # List contact flows command
    flows_parser = subparsers.add_parser('list-flows', help='List Amazon Connect contact flows')
    flows_parser.add_argument('--instance-id', '-i', help='Connect instance ID')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    try:
        if args.command == 'test':
            return cmd_test(args)
        elif args.command == 'status':
            return cmd_status(args)
        elif args.command == 'results':
            return cmd_results(args)
        elif args.command == 'list':
            return cmd_list(args)
        elif args.command == 'cancel':
            return cmd_cancel(args)
        elif args.command == 'provision-number':
            return cmd_provision_number(args)
        elif args.command == 'deploy':
            return cmd_deploy(args)
        elif args.command == 'validate':
            return cmd_validate(args)
        elif args.command == 'list-instances':
            return cmd_list_instances(args)
        elif args.command == 'list-flows':
            return cmd_list_flows(args)
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        print("\nCancelled by user")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_test(args) -> int:
    """Run a voice test"""
    # Load scenario
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {scenario_path}", file=sys.stderr)
        return 1
    
    print(f"Loading scenario: {scenario_path}")
    scenario = load_scenario(scenario_path)
    
    # Validate
    errors = validate_scenario(scenario)
    if errors:
        print("Scenario validation errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    
    # Determine test mode
    mode = getattr(args, 'mode', 'webrtc')
    
    if mode == 'webrtc':
        # WebRTC mode - direct Connect connection
        return cmd_test_webrtc(args, scenario, scenario_path)
    else:
        # PSTN mode - phone call via Chime SDK
        return cmd_test_pstn(args, scenario)


def cmd_test_pstn(args, scenario: Dict) -> int:
    """Run a PSTN-based voice test"""
    # Get target number
    target_number = args.target_number or scenario.get('target', {}).get('phone_number')
    if not target_number:
        print("Error: Target phone number required (--target-number or in scenario)", file=sys.stderr)
        return 1
    
    print(f"Mode: PSTN (phone call via Chime SDK)")
    print(f"Target number: {target_number}")
    print(f"Scenario: {scenario.get('name', 'Unknown')}")
    
    # Get config
    config = get_config()
    
    # Invoke test runner Lambda or run locally
    lambda_arn = config.lambdas.test_runner_arn
    
    if lambda_arn:
        # Invoke Lambda
        print("Invoking test runner Lambda...")
        lambda_client = boto3.client('lambda')
        
        response = lambda_client.invoke(
            FunctionName=lambda_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'start_test',
                'scenario': scenario,
                'target_number': target_number,
                'test_id': args.test_id,
            })
        )
        
        result = json.loads(response['Payload'].read())
    else:
        # Run locally using boto3 directly
        print("Running test locally (Lambda not configured)...")
        result = run_test_locally(scenario, target_number, args.test_id, config)
    
    if result.get('statusCode', 200) != 200:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1
    
    test_id = result.get('test_id', '')
    print(f"\nTest started!")
    print(f"  Test ID: {test_id}")
    print(f"  Status: {result.get('status', 'UNKNOWN')}")
    
    if args.wait:
        print(f"\nWaiting for test to complete (timeout: {args.timeout}s)...")
        return wait_for_test(test_id, args.timeout, config)
    
    print(f"\nTo check status: python -m voice_tester.cli status {test_id}")
    return 0


def cmd_test_webrtc(args, scenario: Dict, scenario_path: Path) -> int:
    """Run a WebRTC-based voice test"""
    
    # Get voice engine setting
    voice_engine = getattr(args, 'voice_engine', 'ai-caller')
    voice = getattr(args, 'voice', 'Joanna')
    
    print(f"Mode: WebRTC (direct Amazon Connect connection)")
    print(f"Voice Engine: {voice_engine} (voice: {voice})")
    print(f"Scenario: {scenario.get('name', 'Unknown')}")
    
    # Get config
    config = get_config()
    
    # Get Connect instance and flow IDs
    instance_id = getattr(args, 'instance_id', None) or os.environ.get('CONNECT_INSTANCE_ID', '')
    contact_flow_id = getattr(args, 'contact_flow_id', None) or os.environ.get('CONTACT_FLOW_ID', '')
    
    if not instance_id:
        print("Error: Connect instance ID required (--instance-id or CONNECT_INSTANCE_ID env var)", file=sys.stderr)
        print("\nTo list available instances: python -m voice_tester list-instances", file=sys.stderr)
        return 1
    
    if not contact_flow_id:
        print("Error: Contact flow ID required (--contact-flow-id or CONTACT_FLOW_ID env var)", file=sys.stderr)
        print(f"\nTo list available flows: python -m voice_tester list-flows --instance-id {instance_id}", file=sys.stderr)
        return 1
    
    print(f"Connect Instance: {instance_id}")
    print(f"Contact Flow: {contact_flow_id}")
    
    # Check for WebRTC Lambda
    webrtc_lambda_arn = os.environ.get('WEBRTC_TESTER_ARN', '') or config.lambdas.webrtc_tester_arn if hasattr(config.lambdas, 'webrtc_tester_arn') else ''
    
    if webrtc_lambda_arn:
        # Invoke WebRTC Lambda
        print("\nInvoking WebRTC tester Lambda...")
        lambda_client = boto3.client('lambda')
        
        response = lambda_client.invoke(
            FunctionName=webrtc_lambda_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'start_test',
                'scenario': scenario,
                'instance_id': instance_id,
                'contact_flow_id': contact_flow_id,
                'test_id': args.test_id,
                'voice_engine': voice_engine,
                'voice': voice,
            })
        )
        
        payload = response['Payload'].read()
        result = json.loads(payload)
        
        if isinstance(result.get('body'), str):
            result = json.loads(result['body'])
    else:
        # Run locally  
        print("\nRunning WebRTC test locally...")
        result = run_webrtc_test_locally(
            scenario, instance_id, contact_flow_id, args.test_id, config,
            voice_engine=voice_engine, voice=voice
        )
    
    if result.get('error'):
        print(f"Error: {result.get('error')}", file=sys.stderr)
        return 1
    
    test_id = result.get('test_id', '')
    print(f"\nTest started!")
    print(f"  Test ID: {test_id}")
    print(f"  Contact ID: {result.get('contact_id', 'N/A')}")
    print(f"  Status: {result.get('status', 'UNKNOWN')}")
    
    # Show conversation if available
    conversation = result.get('conversation', [])
    if conversation:
        print("\n" + "=" * 60)
        print("CONVERSATION:")
        print("-" * 40)
        for turn in conversation:
            speaker = turn.get('speaker', 'unknown')
            text = turn.get('text', '')
            
            if speaker in ['system', 'bot']:
                print(f"  SYSTEM: {text}")
            elif speaker in ['caller', 'ai']:
                print(f"  AI CALLER: {text}")
            else:
                print(f"  [{speaker.upper()}]: {text}")
    
    if args.wait and not conversation:
        print(f"\nWaiting for test to complete (timeout: {args.timeout}s)...")
        return wait_for_test(test_id, args.timeout, config)
    
    print(f"\nTo check status: python -m voice_tester status {test_id}")
    return 0


def run_webrtc_test_locally(
    scenario: Dict,
    instance_id: str,
    contact_flow_id: str,
    test_id: Optional[str],
    config,
    voice_engine: str = 'ai-caller',
    voice: str = 'Joanna',
) -> Dict:
    """Run WebRTC test locally using boto3"""
    import uuid
    
    test_id = test_id or str(uuid.uuid4())
    
    connect = boto3.client('connect')
    connect_participant = boto3.client('connectparticipant')
    
    print(f"  Starting chat contact...")
    
    try:
        # Start chat contact
        chat_response = connect.start_chat_contact(
            InstanceId=instance_id,
            ContactFlowId=contact_flow_id,
            ParticipantDetails={
                'DisplayName': f'AI Voice Tester ({test_id[:8]})'
            },
            InitialMessage={
                'ContentType': 'text/plain',
                'Content': 'Hello'
            },
            ClientToken=test_id,
        )
        
        contact_id = chat_response.get('ContactId', '')
        participant_token = chat_response.get('ParticipantToken', '')
        
        print(f"  Contact ID: {contact_id}")
        
        if not participant_token:
            return {
                'test_id': test_id,
                'contact_id': contact_id,
                'error': 'No participant token received from StartChatContact',
                'status': 'failed',
            }
        
        # Wait for contact to be established
        time.sleep(1)
        
        # Create participant connection - need CONNECTION_CREDENTIALS for API access
        # WEBSOCKET is for real-time streaming, CONNECTION_CREDENTIALS for API calls
        connection_token = ""
        
        # Try CONNECTION_CREDENTIALS only first (for API calls like SendMessage/GetTranscript)
        try:
            print(f"  Creating participant connection...")
            connection = connect_participant.create_participant_connection(
                Type=['CONNECTION_CREDENTIALS'],
                ParticipantToken=participant_token,
            )
            connection_token = connection.get('ConnectionCredentials', {}).get('ConnectionToken', '')
            if connection_token:
                print(f"  Connection established (token length: {len(connection_token)})")
        except Exception as e:
            print(f"  CONNECTION_CREDENTIALS failed: {type(e).__name__}: {e}")
            
            # Try with both types
            try:
                connection = connect_participant.create_participant_connection(
                    Type=['WEBSOCKET', 'CONNECTION_CREDENTIALS'],
                    ParticipantToken=participant_token,
                    ConnectParticipant=True,
                )
                connection_token = connection.get('ConnectionCredentials', {}).get('ConnectionToken', '')
                if connection_token:
                    print(f"  Alternative connection established")
            except Exception as e2:
                print(f"  Alternative also failed: {e2}")
        
        if not connection_token:
            print(f"  No connection token obtained - using participant token directly")
            connection_token = participant_token
        
        # Check for initial welcome message from bot
        time.sleep(2)
        
        try:
            response = connect_participant.get_transcript(
                ConnectionToken=connection_token,
                MaxResults=10,
            )
            transcript_items = response.get('Transcript', [])
            
            # Look for any bot/system messages
            bot_messages = [
                item for item in transcript_items 
                if item.get('ParticipantRole') in ['SYSTEM', 'AGENT', 'BOT']
            ]
            
            if not bot_messages:
                print(f"  Note: No initial bot response. The Lex bot may be voice-only.")
                print(f"  For voice testing, use: --mode pstn --target-number <phone>")
            else:
                for msg in bot_messages:
                    print(f"  Bot: {msg.get('Content', '')[:60]}...")
                    
        except Exception as e:
            print(f"  Could not get initial transcript: {e}")
        
        # Run conversation
        conversation = run_local_conversation(
            scenario=scenario,
            connection_token=connection_token if connection_token else participant_token,
            connect_participant=connect_participant,
            participant_token=participant_token,
            voice_engine=voice_engine,
            voice=voice,
        )
        
        return {
            'test_id': test_id,
            'contact_id': contact_id,
            'status': 'completed',
            'conversation': conversation,
        }
        
    except Exception as e:
        return {
            'test_id': test_id,
            'error': str(e),
            'status': 'failed',
        }


def run_local_conversation(
    scenario: Dict,
    connection_token: str,
    connect_participant,
    participant_token: str = "",
    voice_engine: str = "ai-caller",
    voice: str = "Joanna",
) -> List[Dict]:
    """Run conversation steps locally with AI caller responses"""
    from datetime import datetime, timezone
    import random
    
    conversation = []
    steps = scenario.get('steps', [])
    persona = scenario.get('persona', {})
    
    # Initialize voice client based on selected engine
    voice_client = None
    if voice_engine == 'nova-sonic':
        try:
            from voice_tester.nova_sonic_client import NovaSonicVoiceClient, NovaSonicConfig
            nova_config = NovaSonicConfig(voice_id=voice.lower() if voice else 'matthew')
            voice_client = NovaSonicVoiceClient(nova_config)
            if persona:
                voice_client.set_persona(persona)
            print(f"  Nova Sonic initialized (voice: {nova_config.voice_id})")
        except ImportError as e:
            print(f"  Warning: Nova Sonic module not available: {e}")
            voice_client = None
        except Exception as e:
            print(f"  Warning: Could not initialize Nova Sonic: {e}")
            voice_client = None
    elif voice_engine == 'ai-caller':
        try:
            from voice_tester.ai_caller_client import AICallerClient, AICallerConfig
            ai_config = AICallerConfig(polly_voice_id=voice)
            voice_client = AICallerClient(ai_config)
            if persona:
                voice_client.set_persona(persona)
            print(f"  AI Caller initialized (voice: {voice})")
        except ImportError as e:
            print(f"  Warning: AI Caller module not available: {e}")
            voice_client = None
        except Exception as e:
            print(f"  Warning: Could not initialize AI Caller: {e}")
            voice_client = None
    
    # For backward compatibility
    ai_client = voice_client
    
    # Track messages we've already seen
    seen_message_ids = set()
    
    # Conversation history for AI caller context
    conversation_history = []
    
    for step in steps:
        step_id = step.get('id', 'unknown')
        action = step.get('action', 'listen')
        
        try:
            if action == 'listen':
                # Get transcript
                time.sleep(2)  # Wait for bot response
                
                try:
                    response = connect_participant.get_transcript(
                        ConnectionToken=connection_token,
                        MaxResults=20,
                    )
                    
                    transcript_items = response.get('Transcript', [])
                    
                    # Find new bot messages
                    for item in transcript_items:
                        msg_id = item.get('Id', '')
                        role = item.get('ParticipantRole', '')
                        text = item.get('Content', '')
                        
                        if msg_id not in seen_message_ids:
                            seen_message_ids.add(msg_id)
                            if text and role in ['SYSTEM', 'AGENT', 'BOT']:
                                conversation.append({
                                    'timestamp': datetime.now(timezone.utc).isoformat(),
                                    'speaker': 'system',
                                    'text': text,
                                    'step_id': step_id,
                                })
                                conversation_history.append({
                                    'role': 'system',
                                    'content': text,
                                })
                                print(f"    [SYSTEM]: {text[:80]}...")
                                
                except Exception as e:
                    print(f"  Could not get transcript: {e}")
                        
            elif action == 'speak':
                content = step.get('content', {})
                content_type = content.get('type', 'literal')
                intent = content.get('intent', 'Respond naturally to the system')
                
                # Determine what text to send
                if content_type == 'ai' and ai_client:
                    # Use AI Caller to generate intelligent response
                    last_system_msg = ""
                    for entry in reversed(conversation_history):
                        if entry.get('role') == 'system':
                            last_system_msg = entry.get('content', '')
                            break
                    
                    try:
                        # Generate response using AI Caller (async)
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        text = loop.run_until_complete(
                            ai_client.generate_response(last_system_msg, intent)
                        )
                        loop.close()
                        print(f"    [AI CALLER] Generated: {text}")
                    except Exception as e:
                        print(f"    Warning: AI Caller generation failed: {e}")
                        text = content.get('fallback', 'Yes')
                elif content_type == 'literal':
                    text = content.get('text', 'Yes')
                elif content_type == 'random_choice':
                    text = random.choice(content.get('choices', ['Yes']))
                else:
                    text = 'Yes'
                
                # Send message
                try:
                    connect_participant.send_message(
                        ConnectionToken=connection_token,
                        ContentType='text/plain',
                        Content=text,
                    )
                    print(f"    [AI CALLER]: {text}")
                    
                    # Add to conversation history
                    conversation_history.append({
                        'role': 'caller',
                        'content': text,
                    })
                    
                    # Wait for bot to process and respond
                    time.sleep(2)
                    
                    # Check for bot response
                    try:
                        response = connect_participant.get_transcript(
                            ConnectionToken=connection_token,
                            MaxResults=20,
                        )
                        
                        for item in response.get('Transcript', []):
                            msg_id = item.get('Id', '')
                            role = item.get('ParticipantRole', '')
                            
                            if msg_id not in seen_message_ids:
                                seen_message_ids.add(msg_id)
                                content_text = item.get('Content', '')
                                if content_text:
                                    if role in ['SYSTEM', 'AGENT', 'BOT']:
                                        conversation.append({
                                            'timestamp': datetime.now(timezone.utc).isoformat(),
                                            'speaker': 'system',
                                            'text': content_text,
                                            'step_id': step_id,
                                        })
                                        conversation_history.append({
                                            'role': 'system',
                                            'content': content_text,
                                        })
                                        print(f"    [SYSTEM]: {content_text[:80]}...")
                    except Exception as e:
                        print(f"  Could not get response: {e}")
                        
                except Exception as e:
                    print(f"  Could not send message: {e}")
                
                conversation.append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'speaker': 'caller',
                    'text': text,
                    'step_id': step_id,
                })
                
            elif action == 'wait':
                duration_ms = step.get('duration_ms', 1000)
                time.sleep(duration_ms / 1000)
                
            elif action == 'hangup':
                try:
                    connect_participant.disconnect_participant(
                        ConnectionToken=connection_token,
                    )
                except:
                    pass
                break
                
        except Exception as e:
            print(f"  Step {step_id} error: {e}")
            conversation.append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'speaker': 'error',
                'text': str(e),
                'step_id': step_id,
            })
    
    return conversation


def cmd_status(args) -> int:
    """Check test status"""
    config = get_config()
    
    if config.lambdas.test_runner_arn:
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName=config.lambdas.test_runner_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'check_status',
                'test_id': args.test_id,
            })
        )
        result = json.loads(response['Payload'].read())
    else:
        result = check_status_locally(args.test_id, config)
    
    if result.get('statusCode', 200) != 200:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1
    
    test = result.get('test', {})
    
    print(f"Test ID: {test.get('test_id', args.test_id)}")
    print(f"Status: {test.get('status', 'UNKNOWN')}")
    print(f"Scenario: {test.get('scenario_name', 'Unknown')}")
    print(f"Started: {test.get('started_at', 'Unknown')}")
    
    if test.get('live_status'):
        print(f"Live Status: {test.get('live_status')}")
        print(f"Current Step: {test.get('current_step', 0)}")
        print(f"Conversation Turns: {test.get('conversation_length', 0)}")
    
    if test.get('ended_at'):
        print(f"Ended: {test.get('ended_at')}")
    
    if test.get('error'):
        print(f"Error: {test.get('error')}")
    
    return 0


def cmd_results(args) -> int:
    """Get test results"""
    config = get_config()
    
    if config.lambdas.test_runner_arn:
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName=config.lambdas.test_runner_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'get_results',
                'test_id': args.test_id,
                'include_recording': args.include_recording,
            })
        )
        result = json.loads(response['Payload'].read())
    else:
        result = get_results_locally(args.test_id, args.include_recording, config)
    
    if result.get('statusCode', 200) != 200:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1
    
    test = result.get('test', {})
    
    # Print summary
    print("=" * 60)
    print(f"TEST RESULTS: {test.get('test_id', args.test_id)}")
    print("=" * 60)
    print(f"Scenario: {test.get('scenario_name', 'Unknown')}")
    print(f"Status: {test.get('status', 'UNKNOWN')}")
    print(f"Started: {test.get('started_at', 'Unknown')}")
    print(f"Ended: {test.get('ended_at', 'Unknown')}")
    print()
    
    # Print conversation
    conversation = test.get('conversation', [])
    if conversation:
        print("CONVERSATION:")
        print("-" * 40)
        for turn in conversation:
            speaker = turn.get('speaker', 'unknown')
            text = turn.get('text', '')
            timestamp = turn.get('timestamp', '')
            
            if speaker in ['system', 'bot', 'connect']:
                label = "SYSTEM"
            elif speaker in ['ai', 'ai_spoke', 'caller']:
                label = "AI CALLER"
            else:
                label = speaker.upper()
            
            print(f"[{label}] {text}")
        print()
    
    # Print recordings
    recordings = test.get('recordings', [])
    if recordings:
        print("RECORDINGS:")
        print("-" * 40)
        for rec in recordings:
            print(f"  {rec.get('key', 'unknown')}")
            if 'url' in rec:
                print(f"    URL: {rec['url'][:80]}...")
        print()
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(test, f, indent=2, default=str)
        print(f"Results saved to: {args.output}")
    
    return 0


def cmd_list(args) -> int:
    """List tests"""
    config = get_config()
    
    if config.lambdas.test_runner_arn:
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName=config.lambdas.test_runner_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'list_tests',
                'scenario_name': args.scenario,
                'limit': args.limit,
            })
        )
        result = json.loads(response['Payload'].read())
    else:
        result = list_tests_locally(args.scenario, args.limit, config)
    
    if result.get('statusCode', 200) != 200:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1
    
    tests = result.get('tests', [])
    
    if not tests:
        print("No tests found")
        return 0
    
    print(f"{'TEST ID':<40} {'SCENARIO':<25} {'STATUS':<15} {'STARTED':<20}")
    print("-" * 100)
    
    for test in tests:
        test_id = test.get('test_id', '')[:38]
        scenario = test.get('scenario_name', 'Unknown')[:23]
        status = test.get('status', 'UNKNOWN')[:13]
        started = test.get('started_at', '')[:18]
        
        print(f"{test_id:<40} {scenario:<25} {status:<15} {started:<20}")
    
    return 0


def cmd_cancel(args) -> int:
    """Cancel a test"""
    config = get_config()
    
    if config.lambdas.test_runner_arn:
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName=config.lambdas.test_runner_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'cancel_test',
                'test_id': args.test_id,
            })
        )
        result = json.loads(response['Payload'].read())
    else:
        result = {'statusCode': 400, 'error': 'Local cancel not supported'}
    
    if result.get('statusCode', 200) != 200:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1
    
    print(f"Test {args.test_id} cancelled")
    return 0


def cmd_provision_number(args) -> int:
    """Provision a phone number"""
    config = get_config()
    
    if config.lambdas.test_runner_arn:
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName=config.lambdas.test_runner_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'operation': 'provision_number',
                'area_code': args.area_code,
                'country': args.country,
            })
        )
        result = json.loads(response['Payload'].read())
    else:
        # Run locally
        result = provision_number_locally(args.area_code, args.country)
    
    if result.get('statusCode', 200) != 200:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1
    
    print(f"Phone number ordered: {result.get('phone_number', 'Unknown')}")
    print(f"Order ID: {result.get('order_id', 'Unknown')}")
    print("\nAvailable numbers:")
    for num in result.get('available_numbers', []):
        print(f"  {num}")
    
    return 0


def cmd_deploy(args) -> int:
    """Deploy infrastructure"""
    print("Deploying Voice Test infrastructure...")
    
    if args.destroy:
        cmd = "cdk destroy VoiceTestStack --force"
    else:
        cmd = "cdk deploy VoiceTestStack --require-approval never"
    
    print(f"Running: {cmd}")
    return os.system(cmd)


def cmd_validate(args) -> int:
    """Validate a scenario file"""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {scenario_path}", file=sys.stderr)
        return 1
    
    print(f"Validating: {scenario_path}")
    scenario = load_scenario(scenario_path)
    
    errors = validate_scenario(scenario)
    if errors:
        print("Validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    
    print("Validation PASSED")
    print(f"  Name: {scenario.get('name', 'Unknown')}")
    print(f"  Steps: {len(scenario.get('steps', []))}")
    print(f"  Target: {scenario.get('target', {}).get('phone_number', 'Not specified')}")
    
    return 0


# =============================================================================
# Helper Functions
# =============================================================================

def run_test_locally(scenario: Dict, target_number: str, test_id: Optional[str], config: Config) -> Dict:
    """Run a test without using Lambda"""
    import uuid
    
    test_id = test_id or str(uuid.uuid4())
    
    chime = boto3.client('chime-sdk-voice')
    
    try:
        response = chime.create_sip_media_application_call(
            SipMediaApplicationId=config.chime.sip_media_application_id,
            FromPhoneNumber=config.chime.phone_number,
            ToPhoneNumber=target_number,
            SipHeaders={
                'X-Test-Id': test_id,
                'X-Scenario': scenario.get('name', 'unknown'),
            },
        )
        
        transaction_id = response.get('SipMediaApplicationCall', {}).get('TransactionId', '')
        
        return {
            'statusCode': 200,
            'test_id': test_id,
            'transaction_id': transaction_id,
            'status': 'CALLING'
        }
    except Exception as e:
        return {'statusCode': 500, 'error': str(e)}


def check_status_locally(test_id: str, config: Config) -> Dict:
    """Check status locally using DynamoDB"""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(config.storage.test_results_table or 'VoiceTestResults')
    
    from boto3.dynamodb.conditions import Key
    
    response = table.query(
        KeyConditionExpression=Key('test_id').eq(test_id),
        ScanIndexForward=False,
        Limit=1
    )
    
    items = response.get('Items', [])
    if not items:
        return {'statusCode': 404, 'error': f'Test not found: {test_id}'}
    
    return {'statusCode': 200, 'test': items[0]}


def get_results_locally(test_id: str, include_recording: bool, config: Config) -> Dict:
    """Get results locally"""
    return check_status_locally(test_id, config)


def list_tests_locally(scenario_name: Optional[str], limit: int, config: Config) -> Dict:
    """List tests locally"""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(config.storage.test_results_table or 'VoiceTestResults')
    
    response = table.scan(Limit=limit)
    tests = response.get('Items', [])
    
    if scenario_name:
        tests = [t for t in tests if t.get('scenario_name') == scenario_name]
    
    return {'statusCode': 200, 'tests': tests}


def provision_number_locally(area_code: Optional[str], country: str) -> Dict:
    """Provision a number locally"""
    chime = boto3.client('chime-sdk-voice')
    
    try:
        params = {'Country': country, 'PhoneNumberType': 'Local', 'MaxResults': 5}
        if area_code:
            params['AreaCode'] = area_code
        
        search_response = chime.search_available_phone_numbers(**params)
        available = search_response.get('E164PhoneNumbers', [])
        
        if not available:
            return {'statusCode': 404, 'error': 'No numbers available'}
        
        return {
            'statusCode': 200,
            'available_numbers': available,
            'message': 'Numbers found. Use AWS console or API to complete order.'
        }
    except Exception as e:
        return {'statusCode': 500, 'error': str(e)}


def wait_for_test(test_id: str, timeout: int, config: Config) -> int:
    """Wait for a test to complete"""
    start = time.time()
    
    while time.time() - start < timeout:
        result = check_status_locally(test_id, config)
        
        if result.get('statusCode') != 200:
            print(f"Error checking status: {result.get('error')}")
            return 1
        
        test = result.get('test', {})
        status = test.get('status', 'UNKNOWN')
        
        print(f"  Status: {status}", end='\r')
        
        if status in ['COMPLETED', 'FAILED', 'CANCELLED', 'TEST_COMPLETE']:
            print()
            print(f"\nTest {status.lower()}")
            return 0 if status in ['COMPLETED', 'TEST_COMPLETE'] else 1
        
        time.sleep(2)
    
    print(f"\nTimeout waiting for test (after {timeout}s)")
    return 1


def cmd_list_instances(args) -> int:
    """List Amazon Connect instances"""
    connect = boto3.client('connect')
    
    try:
        response = connect.list_instances()
        instances = response.get('InstanceSummaryList', [])
        
        if not instances:
            print("No Amazon Connect instances found")
            return 0
        
        print(f"\n{'INSTANCE ID':<45} {'ALIAS':<25} {'STATUS':<15}")
        print("-" * 90)
        
        for instance in instances:
            instance_id = instance.get('Id', '')
            alias = instance.get('InstanceAlias', '')[:23]
            status = instance.get('InstanceStatus', '')
            
            print(f"{instance_id:<45} {alias:<25} {status:<15}")
        
        print()
        print("To list contact flows for an instance:")
        print("  python -m voice_tester list-flows --instance-id <INSTANCE_ID>")
        
        return 0
        
    except Exception as e:
        print(f"Error listing instances: {e}", file=sys.stderr)
        return 1


def cmd_list_flows(args) -> int:
    """List Amazon Connect contact flows"""
    instance_id = getattr(args, 'instance_id', None) or os.environ.get('CONNECT_INSTANCE_ID', '')
    
    if not instance_id:
        print("Error: Instance ID required (--instance-id or CONNECT_INSTANCE_ID env var)", file=sys.stderr)
        print("\nTo list instances: python -m voice_tester list-instances", file=sys.stderr)
        return 1
    
    connect = boto3.client('connect')
    
    try:
        response = connect.list_contact_flows(
            InstanceId=instance_id,
            MaxResults=100,
        )
        
        flows = response.get('ContactFlowSummaryList', [])
        
        if not flows:
            print("No contact flows found")
            return 0
        
        print(f"\n{'CONTACT FLOW ID':<45} {'NAME':<35} {'TYPE':<20}")
        print("-" * 100)
        
        for flow in flows:
            flow_id = flow.get('Id', '')
            name = flow.get('Name', '')[:33]
            flow_type = flow.get('ContactFlowType', '')[:18]
            
            print(f"{flow_id:<45} {name:<35} {flow_type:<20}")
        
        print()
        print("To run a test with a specific contact flow:")
        print(f"  python -m voice_tester test <scenario.yaml> --instance-id {instance_id} --contact-flow-id <FLOW_ID>")
        
        return 0
        
    except Exception as e:
        print(f"Error listing contact flows: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
