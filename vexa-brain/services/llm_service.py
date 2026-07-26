from groq import AsyncGroq
from config import settings
from typing import List, Dict, Optional
from services import tracing_service
import logging
import time

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
    json_mode: bool = False,
    agent_name: str = "unknown"
) -> str:
    """Send messages to Groq LLM and return response text.

    Now includes LangSmith tracing for token/latency observability.
    The `agent_name` parameter tags the trace (planner, interactive, recovery, learning).
    """
    client = get_client()
    kwargs = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature or settings.llm_temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    start_time = time.time()

    try:
        response = await client.chat.completions.create(**kwargs)
        latency_ms = (time.time() - start_time) * 1000

        # Extract token usage for tracing
        usage = tracing_service.extract_token_usage(response)
        content = response.choices[0].message.content

        # Log trace to LangSmith
        _log_to_langsmith(
            agent_name=agent_name,
            messages=messages,
            response_text=content,
            usage=usage,
            latency_ms=latency_ms,
            model=settings.llm_model,
            json_mode=json_mode,
        )

        logger.info(
            f"LLM [{agent_name}]: {usage.get('total_tokens', '?')} tokens, "
            f"{latency_ms:.0f}ms"
        )

        return content

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise


def _log_to_langsmith(
    agent_name: str,
    messages: List[Dict[str, str]],
    response_text: str,
    usage: Dict,
    latency_ms: float,
    model: str,
    json_mode: bool,
):
    """Fire-and-forget trace to LangSmith using RunTree (non-blocking)."""
    if not tracing_service._initialized:
        return

    try:
        from langsmith import Client

        client = Client()
        client.create_run(
            name=f"llm/{agent_name}",
            run_type="llm",
            inputs={
                "messages": messages,
                "model": model,
                "json_mode": json_mode,
            },
            outputs={
                "response": response_text,
            },
            extra={
                "metadata": {
                    "agent": agent_name,
                    "model": model,
                    "latency_ms": round(latency_ms, 1),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "runtime": {"type": "groq"},
            },
            project_name=settings.langsmith_project,
        )
    except Exception as e:
        # Tracing should NEVER crash the main flow
        logger.debug(f"LangSmith trace failed (non-fatal): {e}")
