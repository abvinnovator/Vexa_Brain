"""
MemoryAgent — Builds enriched context from multiple sources.

v3.0: Removed phone event behavioral context (no longer tracking events).
Now uses saved agent summary instead of event-based behavioral data.
"""

from services import mongodb_service, knowledge_service, personality_service
from models.request_models import VexaMemory
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


async def enrich(memory: VexaMemory) -> VexaMemory:
    """
    MemoryAgent: Builds context from multiple sources.

    1. Saved agents summary (replaces old MongoDB behavioral data)
    2. OKF knowledge retrieval (smart, relevant-only)
    3. Personality prompt (dynamic style matching)
    """
    uid = memory.user_id

    # ── 1. Agent context (replaces old behavioral context) ──
    try:
        agent_summary = await mongodb_service.get_agent_summary(uid)
        memory.behavioral_context = f"""USER AGENT PROFILE:

{agent_summary}

Current time: {datetime.now().strftime('%A %I:%M %p')}""".strip()

        logger.info(f"MemoryAgent: agent context built for user {uid}")

    except Exception as e:
        logger.error(f"MemoryAgent agent context error: {e}")
        memory.behavioral_context = "No saved agents available."

    # ── 2. OKF Knowledge Retrieval ──
    try:
        memory.knowledge_context = await knowledge_service.query_relevant(
            memory.raw_prompt, uid
        )
        memory.communication_profile = await knowledge_service.get_communication_profile()
        logger.info(f"MemoryAgent: OKF knowledge retrieved ({len(memory.knowledge_context)} chars)")
    except Exception as e:
        logger.error(f"MemoryAgent OKF error: {e}")
        memory.knowledge_context = ""
        memory.communication_profile = ""

    # ── 3. Personality Prompt ──
    try:
        memory.personality_prompt = await personality_service.build_personality_prompt()
    except Exception as e:
        logger.error(f"MemoryAgent personality error: {e}")
        memory.personality_prompt = ""

    return memory
