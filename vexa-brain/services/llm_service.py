from groq import AsyncGroq
from config import settings
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

_client: AsyncGroq = None


def get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def chat(
    messages: List[Dict[str, str]],
    temperature: float = None,
    max_tokens: int = None,
    json_mode: bool = False
) -> str:
    """Send messages to Groq LLM and return response text."""
    client = get_client()
    kwargs = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature or settings.llm_temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise
