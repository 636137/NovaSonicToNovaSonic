import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['SURVEY_TABLE']
table = dynamodb.Table(table_name)


def lambda_handler(event, context):
    """
    Lambda function to handle Lex bot fulfillment for census survey
    """
    print(f"Received Lex event: {json.dumps(event)}")
    
    intent_name = event['sessionState']['intent']['name']
    slots = event['sessionState']['intent']['slots']
    session_attributes = event.get('sessionAttributes', {})
    
    # Handle different intents
    if intent_name == 'StartSurvey':
        return handle_start_survey(event, slots, session_attributes)
    elif intent_name == 'ProvideHouseholdInfo':
        return handle_household_info(event, slots, session_attributes)
    elif intent_name == 'ProvideLanguageInfo':
        return handle_language_info(event, slots, session_attributes)
    elif intent_name == 'ProvideEmploymentInfo':
        return handle_employment_info(event, slots, session_attributes)
    elif intent_name == 'ProvideAgeInfo':
        return handle_age_info(event, slots, session_attributes)
    elif intent_name == 'ProvideHousingInfo':
        return handle_housing_info(event, slots, session_attributes)
    elif intent_name == 'CompleteSurvey':
        return handle_complete_survey(event, slots, session_attributes)
    else:
        return close(event, session_attributes, 'Fulfilled', 
                    'I\'m sorry, I didn\'t understand that.')


def handle_start_survey(event, slots, session_attributes):
    """Handle survey start"""
    session_attributes['survey_started'] = 'true'
    session_attributes['contact_id'] = event.get('sessionId', '')
    
    message = ("Thank you for participating in the census survey. "
               "I'll ask you a few questions. Let's start. "
               "How many people live in your household?")
    
    return elicit_intent(event, session_attributes, message)


def handle_household_info(event, slots, session_attributes):
    """Handle household size information"""
    household_size = slots.get('HouseholdSize', {}).get('value', {}).get('interpretedValue')
    
    if household_size:
        session_attributes['household_size'] = household_size
        message = "Thank you. What is the primary language spoken in your home?"
        return elicit_intent(event, session_attributes, message)
    else:
        return elicit_slot(event, session_attributes, 'ProvideHouseholdInfo', 
                          'HouseholdSize', 
                          'I didn\'t catch that. How many people live in your household?')


def handle_language_info(event, slots, session_attributes):
    """Handle primary language information"""
    language = slots.get('PrimaryLanguage', {}).get('value', {}).get('interpretedValue')
    
    if language:
        session_attributes['primary_language'] = language
        message = "Got it. What is your current employment status? Are you employed, unemployed, retired, or a student?"
        return elicit_intent(event, session_attributes, message)
    else:
        return elicit_slot(event, session_attributes, 'ProvideLanguageInfo', 
                          'PrimaryLanguage', 
                          'What is the primary language spoken in your home?')


def handle_employment_info(event, slots, session_attributes):
    """Handle employment status information"""
    employment = slots.get('EmploymentStatus', {}).get('value', {}).get('interpretedValue')
    
    if employment:
        session_attributes['employment_status'] = employment
        message = "Thank you. What is your age range? Under 18, 18 to 34, 35 to 54, 55 to 64, or 65 and over?"
        return elicit_intent(event, session_attributes, message)
    else:
        return elicit_slot(event, session_attributes, 'ProvideEmploymentInfo', 
                          'EmploymentStatus', 
                          'What is your employment status?')


def handle_age_info(event, slots, session_attributes):
    """Handle age range information"""
    age_range = slots.get('AgeRange', {}).get('value', {}).get('interpretedValue')
    
    if age_range:
        session_attributes['age_range'] = age_range
        message = "Almost done. What type of housing do you live in? House, apartment, condo, or other?"
        return elicit_intent(event, session_attributes, message)
    else:
        return elicit_slot(event, session_attributes, 'ProvideAgeInfo', 
                          'AgeRange', 
                          'What is your age range?')


def handle_housing_info(event, slots, session_attributes):
    """Handle housing type information"""
    housing = slots.get('HousingType', {}).get('value', {}).get('interpretedValue')
    
    if housing:
        session_attributes['housing_type'] = housing
        session_attributes['survey_complete'] = 'true'
        
        # Save complete survey to DynamoDB
        save_survey_data(session_attributes)
        
        message = ("Thank you for completing the census survey! "
                   "Your responses have been recorded. Have a great day!")
        return close(event, session_attributes, 'Fulfilled', message)
    else:
        return elicit_slot(event, session_attributes, 'ProvideHousingInfo', 
                          'HousingType', 
                          'What type of housing do you live in?')


def handle_complete_survey(event, slots, session_attributes):
    """Handle survey completion"""
    session_attributes['survey_complete'] = 'true'
    save_survey_data(session_attributes)
    
    message = "Thank you for your time! Your survey has been completed."
    return close(event, session_attributes, 'Fulfilled', message)


def save_survey_data(session_attributes):
    """Save survey data to DynamoDB"""
    try:
        survey_data = {
            'contact_id': session_attributes.get('contact_id', 'unknown'),
            'timestamp': datetime.utcnow().isoformat(),
            'household_size': session_attributes.get('household_size', ''),
            'primary_language': session_attributes.get('primary_language', ''),
            'employment_status': session_attributes.get('employment_status', ''),
            'age_range': session_attributes.get('age_range', ''),
            'housing_type': session_attributes.get('housing_type', ''),
            'survey_complete': session_attributes.get('survey_complete', 'false')
        }
        
        table.put_item(Item=survey_data)
        print(f"Survey data saved for contact: {survey_data['contact_id']}")
    except Exception as e:
        print(f"Error saving survey data: {str(e)}")


def close(event, session_attributes, fulfillment_state, message):
    """Close the session"""
    return {
        'sessionState': {
            'dialogAction': {
                'type': 'Close'
            },
            'intent': {
                'name': event['sessionState']['intent']['name'],
                'state': fulfillment_state
            },
            'sessionAttributes': session_attributes
        },
        'messages': [
            {
                'contentType': 'PlainText',
                'content': message
            }
        ]
    }


def elicit_intent(event, session_attributes, message):
    """Elicit next intent"""
    return {
        'sessionState': {
            'dialogAction': {
                'type': 'ElicitIntent'
            },
            'sessionAttributes': session_attributes
        },
        'messages': [
            {
                'contentType': 'PlainText',
                'content': message
            }
        ]
    }


def elicit_slot(event, session_attributes, intent_name, slot_name, message):
    """Elicit a specific slot"""
    return {
        'sessionState': {
            'dialogAction': {
                'type': 'ElicitSlot',
                'slotToElicit': slot_name
            },
            'intent': {
                'name': intent_name,
                'state': 'InProgress'
            },
            'sessionAttributes': session_attributes
        },
        'messages': [
            {
                'contentType': 'PlainText',
                'content': message
            }
        ]
    }
