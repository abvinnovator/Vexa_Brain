"""
Learning Service — Post-conversation self-learning processor.

After every conversation turn, this service:
1. Extracts structured facts from the user's message using LLM
2. Classifies each fact into the correct OKF knowledge domain
3. Merges new facts into existing OKF node files (with deduplication)
4. Updates the communication/speech profile
5. Detects and resolves contradictions

Runs asynchronously — never blocks the main response pipeline.
"""

import logging
import re
from typing import List, Dict, Optional
from datetime import datetime

from services import knowledge_service, llm_service

logger = logging.getLogger(__name__)

# Minimum message length to attempt learning (short messages rarely contain new facts)
MIN_WORDS_FOR_LEARNING = 4

# Learning prompt — asks LLM to extract structured facts
EXTRACT_PROMPT = """Analyze this message from the user. Extract ONLY genuinely new, useful insights.
Be very selective — only things worth remembering long-term.

Message: "{user_text}"

Bot reply context: "{bot_reply}"

Output ONLY lines with actual new info, using these exact prefixes:
FACT_PERSONAL: <new personal fact about the user — name, location, education, life events>
FACT_CAREER: <career-related fact — job, interview, work event, company>
FACT_PREFERENCE: <specific preference about how they like things done>
FACT_TEMPORAL: <time-sensitive fact that may expire — e.g., "waiting for results">
SPEECH_PATTERN: <specific slang, unique phrase, or speech pattern>
RELATIONSHIP: <person mentioned with context — who they are, relationship>

If nothing new or noteworthy, output exactly: NOTHING_NEW

Be strict. Most messages will be NOTHING_NEW. Only extract real, specific insights.
Do NOT extract generic observations like "user is chatting" or "user asked a question"."""


# Maps fact types to OKF domain/file
FACT_ROUTING = {
    "FACT_PERSONAL": ("identity", "personal"),
    "FACT_CAREER": ("memory", "career_events"),
    "FACT_PREFERENCE": ("preferences", "communication"),
    "FACT_TEMPORAL": ("memory", "temporal"),
    "SPEECH_PATTERN": ("speech", "profile"),
    "RELATIONSHIP": ("relationships", "contacts"),
}


async def process_conversation(user_msg: str, bot_reply: str, intent: str):
    """
    Main entry point — called after every conversation turn.
    Extracts facts and merges them into the OKF knowledge base.

    This runs asynchronously and should NEVER raise exceptions
    that could affect the main response pipeline.
    """
    try:
        # Skip very short messages
        if len(user_msg.split()) < MIN_WORDS_FOR_LEARNING:
            return

        # Skip pure action intents — nothing personal to learn from "book me an Uber"
        if intent in ("BOOK_RIDE", "ORDER_FOOD", "OPEN_APP"):
            return

        # Extract facts using LLM
        facts = await _extract_facts(user_msg, bot_reply)

        if not facts:
            return

        # Route each fact to the correct OKF node
        merged_count = 0
        for fact_type, fact_text in facts:
            if fact_type in FACT_ROUTING:
                domain, filename = FACT_ROUTING[fact_type]
                await knowledge_service.update_node(
                    domain=domain,
                    filename=filename,
                    new_content=f"- {fact_text}",
                    merge=True
                )
                merged_count += 1

        if merged_count > 0:
            logger.info(f"Learning: merged {merged_count} new fact(s) into knowledge base")

    except Exception as e:
        # Learning should NEVER crash the main flow
        logger.error(f"Learning service error: {e}")


async def _extract_facts(user_msg: str, bot_reply: str) -> List[tuple]:
    """Use LLM to extract structured facts from a conversation turn."""
    prompt = EXTRACT_PROMPT.format(
        user_text=user_msg[:500],  # Cap input to avoid token waste
        bot_reply=bot_reply[:200] if bot_reply else "N/A"
    )

    try:
        messages = [
            {"role": "system", "content": "You are a fact extraction engine. Output ONLY the structured facts or NOTHING_NEW. No explanations."},
            {"role": "user", "content": prompt}
        ]

        response = await llm_service.chat(messages, temperature=0.1, max_tokens=300)
        response = response.strip()

        if "NOTHING_NEW" in response:
            return []

        facts = []
        for line in response.split("\n"):
            line = line.strip()
            if not line:
                continue

            for prefix in FACT_ROUTING.keys():
                if line.startswith(f"{prefix}:"):
                    fact_text = line[len(prefix) + 1:].strip()
                    if fact_text and len(fact_text) > 5:
                        facts.append((prefix, fact_text))
                    break

        return facts

    except Exception as e:
        logger.error(f"Fact extraction failed: {e}")
        return []


async def update_communication_style(user_msg: str):
    """
    Track communication patterns over time.
    Called periodically (not every message) to build the speech profile.
    """
    try:
        # Only analyze longer messages for style
        if len(user_msg.split()) < 6:
            return

        messages = [
            {"role": "system", "content": "You analyze communication style. Be extremely brief."},
            {"role": "user", "content": f"""Analyze this message for UNIQUE communication patterns.
Only report genuinely distinctive patterns (unique slang, language mixing, specific phrasing).

Message: "{user_msg[:300]}"

If nothing distinctive, output: NOTHING_NEW
Otherwise output ONLY: PATTERN: <the specific pattern>"""}
        ]

        response = await llm_service.chat(messages, temperature=0.1, max_tokens=100)

        if "NOTHING_NEW" in response:
            return

        for line in response.strip().split("\n"):
            if line.strip().startswith("PATTERN:"):
                pattern = line.split(":", 1)[1].strip()
                if pattern and len(pattern) > 5:
                    await knowledge_service.update_node(
                        domain="speech",
                        filename="profile",
                        new_content=f"- {pattern}",
                        merge=True
                    )
                    logger.info(f"Speech pattern learned: {pattern}")

    except Exception as e:
        logger.error(f"Communication style update error: {e}")
