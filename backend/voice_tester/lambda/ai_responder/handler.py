"""
AI Responder Lambda

Uses Amazon Bedrock (Claude) to generate contextual AI responses
based on the test scenario and conversation history.

This Lambda is invoked when the audio processor detects speech from
the system under test and needs to generate an appropriate response.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import boto3

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')
CALL_STATE_TABLE = os.environ.get('CALL_STATE_TABLE', 'VoiceTestCallState')


class AICallerPersona:
    """
    Manages the AI caller's persona and generates contextual responses.
    """
    
    def __init__(self, persona_config: Dict[str, Any]):
        self.name = persona_config.get('name', 'Standard Caller')
        self.attributes = persona_config.get('attributes', {})
        self.background = persona_config.get('background', '')
        self.behaviors = persona_config.get('behaviors', {})
        
        # Build system prompt based on persona
        self.system_prompt = self._build_system_prompt()
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for Bedrock based on persona configuration"""
        
        prompt = f"""You are playing the role of a person calling an automated phone system for testing purposes.

Your persona: {self.name}

Background:
{self.background if self.background else "You are a standard caller testing the system. Respond naturally but stay focused on the test scenario."}

Speaking style:
- Speaking rate: {self.attributes.get('speaking_rate', 'normal')}
- Patience level: {self.attributes.get('patience', 'normal')}
- Clarity: {self.attributes.get('clarity', 'clear')}

Behavioral traits:
- Asks for clarification when confused: {self.behaviors.get('asks_clarification', True)}
- May interrupt: {self.behaviors.get('interrupts', False)}
- Makes occasional mistakes: {self.behaviors.get('makes_mistakes', False)}

IMPORTANT RULES:
1. Respond as if you are on a phone call - keep responses brief and natural
2. Only say what you would actually speak aloud - no actions, no descriptions
3. Match the energy and pace appropriate for a phone conversation
4. If the system asks a question, answer it directly
5. If you don't understand something, ask for clarification (if that's in character)
6. Stay focused on completing the test scenario objectives

Output ONLY the exact words you would say. No quotes, no descriptions, no stage directions.
"""
        return prompt
    
    def generate_response(
        self,
        heard_text: str,
        conversation_history: List[Dict],
        scenario_context: Dict,
        current_step: Dict
    ) -> str:
        """
        Generate an appropriate response using Bedrock.
        
        Args:
            heard_text: What the system just said (transcribed)
            conversation_history: List of previous conversation turns
            scenario_context: The test scenario configuration
            current_step: Current step in the test scenario
        
        Returns:
            The text response to speak
        """
        
        # Build conversation context
        messages = self._build_messages(
            heard_text, 
            conversation_history, 
            scenario_context,
            current_step
        )
        
        # Call Bedrock
        try:
            response = bedrock_runtime.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 150,  # Keep responses brief for voice
                    "temperature": 0.7,
                    "system": self.system_prompt,
                    "messages": messages
                })
            )
            
            response_body = json.loads(response['body'].read())
            ai_text = response_body['content'][0]['text'].strip()
            
            # Clean up the response
            ai_text = self._clean_response(ai_text)
            
            logger.info(f"AI generated response: {ai_text}")
            return ai_text
            
        except Exception as e:
            logger.error(f"Error calling Bedrock: {e}")
            # Fallback response
            return self._get_fallback_response(current_step)
    
    def _build_messages(
        self,
        heard_text: str,
        conversation_history: List[Dict],
        scenario_context: Dict,
        current_step: Dict
    ) -> List[Dict]:
        """Build the messages array for Bedrock"""
        
        messages = []
        
        # Add scenario context as first user message
        scenario_prompt = f"""TEST SCENARIO: {scenario_context.get('name', 'Voice Test')}
        
Objective: {scenario_context.get('description', 'Test the automated phone system')}

Current step: {current_step.get('description', 'Respond naturally')}
Expected outcome: {current_step.get('expect', {}).get('patterns', ['Respond appropriately'])}

"""
        if current_step.get('content', {}).get('type') == 'ai_generated':
            scenario_prompt += f"\nIntent for this response: {current_step.get('content', {}).get('intent', 'Respond naturally')}"
        
        messages.append({
            "role": "user",
            "content": scenario_prompt
        })
        
        messages.append({
            "role": "assistant", 
            "content": "I understand. I'll respond as the caller in this test scenario."
        })
        
        # Add conversation history
        for turn in conversation_history[-10:]:  # Last 10 turns for context
            speaker = turn.get('speaker', '')
            text = turn.get('text', '')
            
            if speaker in ['system', 'bot', 'connect']:
                messages.append({"role": "user", "content": f"[System says]: {text}"})
            elif speaker in ['ai', 'ai_spoke', 'caller']:
                messages.append({"role": "assistant", "content": text})
        
        # Add the new input
        if heard_text:
            messages.append({
                "role": "user",
                "content": f"[System says]: {heard_text}\n\nRespond as the caller:"
            })
        
        return messages
    
    def _clean_response(self, text: str) -> str:
        """Clean up AI response for voice output"""
        # Remove any stage directions or descriptions
        text = text.strip()
        
        # Remove quotes if present
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        
        # Remove common AI artifacts
        prefixes_to_remove = [
            "[Caller]:", "[Response]:", "Response:", "Caller:", 
            "[Speaking]:", "I say:", "I would say:"
        ]
        for prefix in prefixes_to_remove:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        
        return text
    
    def _get_fallback_response(self, current_step: Dict) -> str:
        """Get a fallback response if AI fails"""
        step_type = current_step.get('content', {}).get('type', '')
        
        if step_type == 'literal':
            return current_step.get('content', {}).get('text', "Yes")
        
        # Generic fallbacks
        return "Could you please repeat that?"


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Main handler for generating AI responses.
    
    Expected event structure:
    {
        "call_id": "xxx",
        "heard_text": "Welcome to the census survey...",
        "request_type": "generate_response" | "evaluate_response"
    }
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    call_id = event.get('call_id', '')
    heard_text = event.get('heard_text', '')
    request_type = event.get('request_type', 'generate_response')
    
    if not call_id:
        return {
            'statusCode': 400,
            'error': 'call_id is required'
        }
    
    # Get call state
    call_state = get_call_state(call_id)
    if not call_state:
        return {
            'statusCode': 404,
            'error': f'Call state not found for {call_id}'
        }
    
    if request_type == 'generate_response':
        return handle_generate_response(call_id, heard_text, call_state)
    elif request_type == 'evaluate_response':
        return handle_evaluate_response(call_id, heard_text, call_state)
    else:
        return {
            'statusCode': 400,
            'error': f'Unknown request_type: {request_type}'
        }


def handle_generate_response(
    call_id: str, 
    heard_text: str, 
    call_state: Dict
) -> Dict[str, Any]:
    """Generate an AI response for the call"""
    
    # Get persona and scenario from call state
    scenario_data = call_state.get('scenario_data', {})
    persona_config = scenario_data.get('persona', {
        'name': 'Standard Caller',
        'attributes': {'speaking_rate': 'normal', 'patience': 'normal'},
        'background': 'A person testing the phone system.',
        'behaviors': {'asks_clarification': True}
    })
    
    # Create persona
    persona = AICallerPersona(persona_config)
    
    # Get current step
    current_step_index = call_state.get('current_step_index', 0)
    steps = scenario_data.get('steps', [])
    current_step = steps[current_step_index] if current_step_index < len(steps) else {}
    
    # Get conversation history
    conversation = call_state.get('conversation', [])
    
    # Add what we heard to conversation
    if heard_text:
        add_to_conversation(call_id, 'system', heard_text)
        conversation.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'speaker': 'system',
            'text': heard_text
        })
    
    # Check if current step expects AI-generated response
    step_content = current_step.get('content', {})
    if step_content.get('type') == 'literal':
        # Use literal text from scenario
        response_text = step_content.get('text', 'Yes')
    elif step_content.get('type') == 'random_choice':
        # Pick from choices
        import random
        choices = step_content.get('choices', ['Yes'])
        response_text = random.choice(choices)
    else:
        # Generate AI response
        response_text = persona.generate_response(
            heard_text=heard_text,
            conversation_history=conversation,
            scenario_context=scenario_data,
            current_step=current_step
        )
    
    # Add AI response to conversation
    add_to_conversation(call_id, 'ai_spoke', response_text)
    
    # Update step index
    update_call_state(call_id, {'current_step_index': current_step_index + 1})
    
    return {
        'statusCode': 200,
        'response_text': response_text,
        'call_id': call_id,
        'step_completed': current_step.get('id', f'step_{current_step_index}')
    }


def handle_evaluate_response(
    call_id: str,
    heard_text: str,
    call_state: Dict
) -> Dict[str, Any]:
    """
    Evaluate if the system response matches expectations.
    
    Uses AI to determine if the response indicates success or failure.
    """
    scenario_data = call_state.get('scenario_data', {})
    current_step_index = call_state.get('current_step_index', 0)
    steps = scenario_data.get('steps', [])
    
    if current_step_index == 0:
        current_step_index = max(0, len([c for c in call_state.get('conversation', []) if c.get('speaker') == 'ai_spoke']))
    
    current_step = steps[current_step_index - 1] if current_step_index > 0 and current_step_index <= len(steps) else {}
    
    expected_patterns = current_step.get('expect', {}).get('patterns', [])
    
    # Simple pattern matching first
    import re
    matches = []
    for pattern in expected_patterns:
        if re.search(pattern, heard_text, re.IGNORECASE):
            matches.append(pattern)
    
    if matches:
        return {
            'statusCode': 200,
            'evaluation': 'pass',
            'matched_patterns': matches,
            'heard_text': heard_text
        }
    
    # If no pattern match, use AI to evaluate
    try:
        eval_prompt = f"""Evaluate if this system response indicates successful test progress.

Test step: {current_step.get('description', 'No description')}
Expected patterns: {expected_patterns}
System said: "{heard_text}"

Does this response indicate:
1. SUCCESS - The system responded appropriately to the test input
2. FAILURE - The system showed an error or unexpected response
3. CONTINUE - The response is neutral, continue with the test
4. UNCLEAR - Cannot determine from this response

Respond with just one word: SUCCESS, FAILURE, CONTINUE, or UNCLEAR"""

        response = bedrock_runtime.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 50,
                "temperature": 0,
                "messages": [{"role": "user", "content": eval_prompt}]
            })
        )
        
        response_body = json.loads(response['body'].read())
        evaluation = response_body['content'][0]['text'].strip().upper()
        
        # Normalize evaluation
        if evaluation not in ['SUCCESS', 'FAILURE', 'CONTINUE', 'UNCLEAR']:
            evaluation = 'CONTINUE'
        
        return {
            'statusCode': 200,
            'evaluation': evaluation.lower(),
            'matched_patterns': [],
            'heard_text': heard_text,
            'ai_evaluated': True
        }
        
    except Exception as e:
        logger.error(f"Error evaluating response: {e}")
        return {
            'statusCode': 200,
            'evaluation': 'continue',
            'matched_patterns': [],
            'heard_text': heard_text,
            'error': str(e)
        }


# =============================================================================
# Helper Functions
# =============================================================================

def get_call_state(call_id: str) -> Optional[Dict]:
    """Get call state from DynamoDB"""
    table = dynamodb.Table(CALL_STATE_TABLE)
    try:
        response = table.get_item(Key={'call_id': call_id})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting call state: {e}")
        return None


def update_call_state(call_id: str, updates: Dict) -> None:
    """Update call state in DynamoDB"""
    table = dynamodb.Table(CALL_STATE_TABLE)
    
    update_expr_parts = []
    expr_attr_values = {}
    expr_attr_names = {}
    
    for key, value in updates.items():
        safe_key = f"#{key}"
        expr_attr_names[safe_key] = key
        expr_attr_values[f":{key}"] = value
        update_expr_parts.append(f"{safe_key} = :{key}")
    
    if update_expr_parts:
        try:
            table.update_item(
                Key={'call_id': call_id},
                UpdateExpression="SET " + ", ".join(update_expr_parts),
                ExpressionAttributeNames=expr_attr_names,
                ExpressionAttributeValues=expr_attr_values
            )
        except Exception as e:
            logger.error(f"Error updating call state: {e}")


def add_to_conversation(call_id: str, speaker: str, text: str) -> None:
    """Add entry to conversation log"""
    table = dynamodb.Table(CALL_STATE_TABLE)
    
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'speaker': speaker,
        'text': text
    }
    
    try:
        table.update_item(
            Key={'call_id': call_id},
            UpdateExpression="SET conversation = list_append(if_not_exists(conversation, :empty), :entry)",
            ExpressionAttributeValues={
                ':entry': [entry],
                ':empty': []
            }
        )
    except Exception as e:
        logger.error(f"Error adding to conversation: {e}")
