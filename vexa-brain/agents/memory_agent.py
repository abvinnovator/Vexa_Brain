"""
MemoryAgent — Builds enriched context from multiple sources.

v3.0: Enhanced retrieval with LLM-powered semantic search.
Always includes identity baseline for personal context.
"""

from services import knowledge_service, personality_service
from models.request_models import VexaMemory
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


async def enrich(memory: VexaMemory) -> VexaMemory:
    """
    MemoryAgent: Builds context from multiple sources.

    1. Current time
    2. OKF knowledge retrieval (LLM-expanded semantic search)
    3. Personality prompt (dynamic style matching)
    """
    uid = memory.user_id

    # ── 1. Situational context ──
    memory.behavioral_context = f"Current time: {datetime.now().strftime('%A %d %B %Y, %I:%M %p')}"

    # ── 2. OKF Knowledge Retrieval (Enhanced v3.0) ──
    try:
        memory.knowledge_context = await knowledge_service.query_relevant(
            memory.raw_prompt, uid
        )
        memory.communication_profile = await knowledge_service.get_communication_profile()

        context_len = len(memory.knowledge_context)
        logger.info(f"MemoryAgent: OKF knowledge retrieved ({context_len} chars)")

        if context_len < 50:
            logger.warning(f"MemoryAgent: Very little knowledge context retrieved for prompt: '{memory.raw_prompt[:60]}'")

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
