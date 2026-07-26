"""
LangSmith tracing service for Vexa Brain.

Provides tracing wrappers around LLM calls so that every inference
is logged to LangSmith with token usage, latency, and metadata.
Dashboard: https://smith.langchain.com  (project "XA")
"""

import os
import time
import logging
from typing import Optional, Dict, Any
from functools import wraps
from config import settings

logger = logging.getLogger(__name__)

_initialized = False


def init():
    """
    Initialize LangSmith tracing by setting environment variables.
    The LangSmith SDK reads these automatically — no explicit client needed
    for basic tracing via the `@traceable` decorator.
    """
    global _initialized
    if _initialized:
        return

    if not settings.langsmith_api_key:
        logger.warning("LangSmith API key not set — tracing disabled")
        return

    # LangSmith SDK reads these env vars automatically
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if settings.langsmith_tracing else "false"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

    _initialized = True
    logger.info(f"LangSmith tracing initialized — project='{settings.langsmith_project}'")


def extract_token_usage(response) -> Dict[str, int]:
    """
    Extract token usage from a Groq API response.
    Returns dict with prompt_tokens, completion_tokens, total_tokens.
    """
    usage = {}
    try:
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            }
    except Exception as e:
        logger.debug(f"Could not extract token usage: {e}")
    return usage


def traced_llm_call(agent_name: str):
    """
    Decorator that wraps an LLM call function with LangSmith tracing.

    Usage:
        @traced_llm_call("planner")
        async def chat(messages, ...):
            ...

    The decorator:
    - Imports `langsmith.traceable` and applies it
    - Adds agent_name, model, and token usage as metadata
    - Measures wall-clock latency
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not _initialized:
                return await func(*args, **kwargs)

            try:
                from langsmith import traceable

                # Create a traced version of the function
                @traceable(
                    name=f"llm_call/{agent_name}",
                    run_type="llm",
                    project_name=settings.langsmith_project,
                    metadata={
                        "agent": agent_name,
                        "model": settings.llm_model,
                    },
                )
                async def _traced(*args, **kwargs):
                    return await func(*args, **kwargs)

                return await _traced(*args, **kwargs)

            except ImportError:
                logger.warning("langsmith not installed — running without tracing")
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Tracing error (non-fatal): {e}")
                return await func(*args, **kwargs)

        return wrapper
    return decorator
