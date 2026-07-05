"""
Personality Service — Dynamic response style matching.

Builds a compact personality instruction for the LLM based on:
1. The user's speech profile (from OKF)
2. The user's communication preferences
3. Conversation context (time of day, intent type)

The goal: Vexa should sound like a friend who knows you, not a generic bot.
"""

import logging
from datetime import datetime
from services import knowledge_service

logger = logging.getLogger(__name__)


async def build_personality_prompt(intent: str = "CONVERSATION") -> str:
    """
    Generate a compact personality instruction block for the LLM.

    Returns a string that goes into the system/user prompt to calibrate
    how the LLM responds — matching the user's communication style.
    """
    # Get speech profile from OKF
    speech_profile = await knowledge_service.get_communication_profile()

    # Get communication preferences
    comm_prefs = knowledge_service.get_node_content("preferences", "communication")

    # Time-based tone adjustment
    hour = datetime.now().hour
    if 6 <= hour < 12:
        time_tone = "It's morning — be energetic but not over the top."
    elif 12 <= hour < 17:
        time_tone = "It's afternoon — be focused and productive."
    elif 17 <= hour < 22:
        time_tone = "It's evening — be relaxed and casual."
    else:
        time_tone = "It's late night — be calm and brief. He's probably winding down."

    # Intent-based adaptation
    if intent in ("BOOK_RIDE", "ORDER_FOOD", "OPEN_APP", "SEARCH"):
        intent_tone = "He wants to get something done. Be efficient — confirm the action and execute. No unnecessary chat."
    else:
        intent_tone = "This is conversational. Be natural, warm, and genuine. Connect to what you know about him."

    # Build the compact personality block
    personality = f"""PERSONALITY RULES (match Vamsi's style):
- Talk like a smart, chill friend — not a corporate bot.
- Call him "Vamsi" naturally. Be casual, warm, direct.
- No emojis. Brief but genuine.
- Match his tech level — he knows system design, cloud, agentic AI.
- If he's brief, be brief. If he elaborates, engage more.
- He mixes Telugu and English — that's normal, don't make it weird.
- {time_tone}
- {intent_tone}"""

    # Add learned patterns if available
    if speech_profile and speech_profile != "No speech profile available yet. Learn from conversations.":
        # Take a compact excerpt
        profile_lines = speech_profile.split("\n")[:8]
        personality += "\n\nLEARNED COMMUNICATION PATTERNS:\n" + "\n".join(profile_lines)

    if comm_prefs:
        # Extract just the key points
        pref_lines = [l.strip() for l in comm_prefs.split("\n") if l.strip().startswith("- ")][:4]
        if pref_lines:
            personality += "\n\nUSER PREFERENCES:\n" + "\n".join(pref_lines)

    return personality
