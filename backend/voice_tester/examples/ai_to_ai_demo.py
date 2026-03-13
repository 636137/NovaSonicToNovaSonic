#!/usr/bin/env python3
"""
AI-to-AI Conversation using Nova Sonic

Two Nova Sonic instances have a real conversation:
- Customer (Sarah): Calling about a suspicious charge
- Agent (Alex): Customer service representative

This demonstrates pure AI-to-AI voice conversation using Amazon Nova Sonic.
"""

import asyncio
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from nova_sonic import NovaSonicSession, resample_24k_to_16k, save_wav, play_audio

# Polly for initial bootstrap (one sentence to start)
polly = boto3.client('polly', region_name='us-east-1')


def polly_audio(text: str, voice: str = "Ruth") -> bytes:
    """Generate 16kHz PCM from Polly for bootstrap."""
    resp = polly.synthesize_speech(
        Text=text, 
        OutputFormat='pcm', 
        VoiceId=voice, 
        SampleRate='16000', 
        Engine='neural'
    )
    return resp['AudioStream'].read()


async def run_conversation(num_turns: int = 6, play_live: bool = False):
    """
    Run an AI-to-AI conversation.
    
    Args:
        num_turns: Number of conversation turns
        play_live: Play audio as it's generated
    """
    
    # Define personas
    customer_prompt = """You are Sarah, a customer calling about a suspicious charge.

SITUATION: You noticed $47.99 from "STREAMTECH SERVICES" and don't recognize it.

BEHAVIOR:
- Speak naturally like a real phone caller
- Express mild concern about the charge
- Your name is Sarah Miller if asked
- If they explain it's a streaming subscription, try to recall if you signed up
- Keep responses SHORT - 1-2 sentences maximum
- End call politely when resolved"""

    agent_prompt = """You are Alex, a customer service rep at ABC Bank.

ROLE:
- Greet warmly
- The $47.99 is their StreamTech Plus subscription (set up 3 months ago)
- Verify identity if needed (ask for name)
- Explain the charge clearly
- Offer to block merchant if they want to cancel
- Keep responses SHORT - 1-2 sentences
- Be warm and helpful"""

    print("=" * 60)
    print("🎭 AI-to-AI CONVERSATION")
    print("=" * 60)
    print("Customer (Sarah/Tiffany) <---> Agent (Alex/Matthew)")
    print("-" * 60)
    
    # Track conversation audio
    conversation = []  # List of (speaker, audio, sample_rate)
    
    async with NovaSonicSession("tiffany", customer_prompt) as customer, \
               NovaSonicSession("matthew", agent_prompt) as agent:
        
        print("[CUSTOMER] Connected (voice: tiffany)")
        print("[AGENT] Connected (voice: matthew)")
        print("\n" + "=" * 60)
        print("🎬 CONVERSATION START")
        print("=" * 60)
        
        # Turn 1: Bootstrap with Polly (customer's opening)
        print("\n--- Turn 1: Customer calls in ---")
        opening = "Hi, I'm calling about a charge on my statement. I see forty-seven ninety-nine from something called StreamTech Services, and I don't recognize it."
        bootstrap_audio = polly_audio(opening, "Ruth")
        
        print(f"🔵 CUSTOMER: {opening}")
        conversation.append(("CUSTOMER", bootstrap_audio, 16000))
        
        if play_live:
            play_audio(bootstrap_audio, 16000)
        
        # Send to agent and get response
        print("\n--- Turn 2: Agent responds ---")
        agent_response = await agent.send_audio(bootstrap_audio)
        
        if agent_response:
            print(f"🟢 AGENT: {agent.all_text[-1] if agent.all_text else ''}")
            conversation.append(("AGENT", agent_response, 24000))
            
            if play_live:
                play_audio(agent_response, 24000)
            
            # Continue conversation - alternating turns
            current_audio = agent_response
            turn = 3
            
            while turn <= num_turns and current_audio:
                # Resample for input
                audio_16k = resample_24k_to_16k(current_audio)
                
                if turn % 2 == 1:  # Customer's turn (odd)
                    print(f"\n--- Turn {turn}: Customer responds ---")
                    current_audio = await customer.send_audio(audio_16k)
                    if current_audio:
                        print(f"🔵 CUSTOMER: {customer.all_text[-1] if customer.all_text else ''}")
                        conversation.append(("CUSTOMER", current_audio, 24000))
                else:  # Agent's turn (even)
                    print(f"\n--- Turn {turn}: Agent responds ---")
                    current_audio = await agent.send_audio(audio_16k)
                    if current_audio:
                        print(f"🟢 AGENT: {agent.all_text[-1] if agent.all_text else ''}")
                        conversation.append(("AGENT", current_audio, 24000))
                
                if play_live and current_audio:
                    play_audio(current_audio, 24000)
                    
                turn += 1
        
        print("\n" + "=" * 60)
        print("🎬 CONVERSATION END")
        print("=" * 60)
        
        # Print transcript
        print("\n📜 TRANSCRIPT:")
        print("🔵 CUSTOMER:", customer.all_text)
        print("🟢 AGENT:", agent.all_text)
    
    return conversation


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='AI-to-AI conversation with Nova Sonic')
    parser.add_argument('--turns', type=int, default=6, help='Number of conversation turns')
    parser.add_argument('--live', action='store_true', help='Play audio live during conversation')
    parser.add_argument('--save', type=str, help='Save conversation to WAV files with this prefix')
    parser.add_argument('--playback', action='store_true', help='Play back full conversation at end')
    
    args = parser.parse_args()
    
    conversation = await run_conversation(num_turns=args.turns, play_live=args.live)
    
    # Save audio files
    if args.save:
        os.makedirs('voice_output', exist_ok=True)
        
        customer_audio = b''.join(a for s, a, r in conversation if s == "CUSTOMER" and r == 24000)
        agent_audio = b''.join(a for s, a, r in conversation if s == "AGENT")
        
        if customer_audio:
            save_wav(customer_audio, f'voice_output/{args.save}_customer.wav', 24000)
        if agent_audio:
            save_wav(agent_audio, f'voice_output/{args.save}_agent.wav', 24000)
        print(f"\n💾 Saved to voice_output/{args.save}_*.wav")
    
    # Playback
    if args.playback:
        print("\n" + "=" * 60)
        print("🔊 PLAYING BACK CONVERSATION")
        print("=" * 60)
        
        for speaker, audio, rate in conversation:
            icon = "🔵" if speaker == "CUSTOMER" else "🟢"
            print(f"\n{icon} {speaker} speaking...")
            play_audio(audio, rate)
        
        print("\n✅ Playback complete!")


if __name__ == "__main__":
    asyncio.run(main())
