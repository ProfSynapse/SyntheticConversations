import os
import json
import logging
import random
import uuid
from api_clients import (
    generate_response_openai,
    generate_response_claude,
    generate_response_groq,
    generate_response_gemini,
    generate_response_local,
    gemini_api_keys
)
from google.api_core import exceptions
import google.generativeai as genai

# Configure logging
logging.basicConfig(filename='synapse_thoughts.log', level=logging.INFO, format='%(asctime)s - %(message)s')

def generate_conversation(note, output_file, config, use_openai, use_claude, use_groq, use_gemini, use_openrouter):
    model_conversation_history = []
    user_conversation_history = []
    conversation_id = str(uuid.uuid4())
    api_key_cycle_count = 0
    max_api_key_cycles = len(gemini_api_keys)  # Add this line to calculate max_api_key_cycles

    if use_gemini:
        gemini_model = genai.GenerativeModel(config['gemini_details']['model_id'])
    else:
        gemini_model = None

    def generate_response(role, message, response_type=None):
        nonlocal api_key_cycle_count

        # Debug statement to check the type and content of max_tokens configuration
        logging.info(f"Config max_tokens: {config['generation_parameters']['max_tokens']}")
        if not isinstance(config['generation_parameters']['max_tokens'], dict):
            raise ValueError("config['generation_parameters']['max_tokens'] should be a dictionary")

        max_tokens = config['generation_parameters']['max_tokens'].get(response_type or role, config['generation_parameters']['max_tokens']['default'])

        if use_openai:
            return generate_response_openai(model_conversation_history, role, message, config['openai_details']['model_id'], config['openai_api_key'], config['generation_parameters']['temperature'], max_tokens)
        elif use_claude:
            return generate_response_claude(model_conversation_history, role, message, config['claude_details']['model_id'], config['claude_api_key'], config['generation_parameters']['temperature'], max_tokens)
        elif use_groq:
            return generate_response_groq(model_conversation_history, role, message, config['groq_details']['model_id'], config['generation_parameters']['temperature'], max_tokens)
        elif use_gemini:
            logging.info(f"Attempting to generate response with Gemini API. Max API key cycles: {max_api_key_cycles}")
            logging.info(f"Available Gemini API keys: {gemini_api_keys}")
            while api_key_cycle_count < max_api_key_cycles:
                response = generate_response_gemini(message, gemini_model, api_key_cycle_count)
                if response is not None:
                    return response
                api_key_cycle_count += 1
            logging.error("Reached maximum API key cycles. Please try again later.")
            raise exceptions.ResourceExhausted("Reached maximum API key cycles. Please try again later.")
        else:
            return generate_response_local(model_conversation_history, role, message, config, max_tokens, response_type)

    def generate_and_append_response(role, prompt, model_conversation_history, user_conversation_history, output_file, conversation_id, turn, response_type, name):
        logging.info(f"Conversation ID: {conversation_id}, Turn: {turn}, Role: {role}")
        logging.info(random.choice(config['synapse_thoughts']))
        response = generate_response(role, prompt, response_type)
        if response is None:
            logging.warning(f"Failed to generate {role} response.")
            return None

        if name == "Professor":
            response = f"🧙🏿‍♂️: {response}"

        model_conversation_history.append({"role": role, "content": response, "name": name})
        
        if role == "user" or name == "Professor":
            user_conversation_history.append({"role": role, "content": response, "name": name})
        
        append_conversation_to_json({"role": role, "name": name, "content": response, "conversation_id": conversation_id, "turn": turn, "token_count": len(response)}, output_file, conversation_id)
        
        return response

    # Initial user problem generation with document access
    user_problem = generate_response("user", f"{config['system_prompts']['user_system_prompt']}\n\nDocument:\n{note['content']}\n\n**You are now Joseph!**, and are about to begin your conversation with Prof. Come up with the problem you face based on the provided text, and respond in the first person as Joseph:**", response_type="user")
    if user_problem is None or not user_problem.strip():
        logging.warning("Failed to generate user problem or user problem is empty.")
        return None

    model_conversation_history.append({"role": "user", "content": user_problem, "name": "Joseph"})
    user_conversation_history.append({"role": "user", "content": user_problem, "name": "Joseph"})
    append_conversation_to_json({"role": "user", "name": "Joseph", "content": user_problem, "conversation_id": conversation_id, "turn": 0, "token_count": len(user_problem)}, output_file, conversation_id)

    num_turns = random.randint(6, 10)  # Randomly choose the number of turns between 6 and 10

    for turn in range(1, num_turns + 1):
        # CoR Generation
        cor_prompt = f"{config['system_prompts']['cor_system_prompt']}\n\nConversation History:\n{model_conversation_history}\n\nFilled-in CoR:"
        cor_response = generate_and_append_response("assistant", cor_prompt, model_conversation_history, user_conversation_history, output_file, conversation_id, turn, response_type="cor", name="CoR")
        if cor_response is None or not cor_response.strip():
            return model_conversation_history

        # Professor Synapse Generation
        synapse_prompt = f"{config['system_prompts']['synapse_system_prompt']}\n\nConversation History:\n{model_conversation_history}\n\n🧙🏿‍♂️:"
        synapse_response = generate_and_append_response("assistant", synapse_prompt, model_conversation_history, user_conversation_history, output_file, conversation_id, turn, response_type="professor_synapse", name="Professor")
        if synapse_response is None or not synapse_response.strip():
            return model_conversation_history

        # User follow-up prompt without document access but using the system prompt and previous user conversation history
        user_followup_prompt = f"{config['system_prompts']['user_system_prompt']}\n\nConversation History:\n{user_conversation_history}\n\nBased on Professor Synapse's previous response, ask a specific NEW question that builds upon the information provided and helps deepen your understanding of the topic. Respond in first person as Joseph:"
        user_followup_response = generate_and_append_response("user", user_followup_prompt, model_conversation_history, user_conversation_history, output_file, conversation_id, turn, response_type="user", name="Joseph")
        if user_followup_response is None or not user_followup_response.strip():
            return model_conversation_history

    return model_conversation_history

def append_conversation_to_json(conversation, output_file, conversation_id):
    if not os.path.exists(output_file):
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump([], f)

    with open(output_file, 'r', encoding='utf-8') as f:
        try:
            conversations = json.load(f)
        except json.JSONDecodeError:
            conversations = []

    conversations.append(conversation)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(conversations, f, indent=4)

def format_output(conversation):
    return conversation

def finalize_json_output(output_file):
    pass