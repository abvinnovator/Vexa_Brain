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


_client = None


def _get_client():
    """One shared LangSmith client — its background thread batches post/patch calls so
    tracing never blocks the event loop. (A Client per call spawned a thread per call.)"""
    global _client
    if _client is None:
        from langsmith import Client
        _client = Client(api_key=settings.langsmith_api_key)
    return _client


def start_llm_trace(agent_name: str, messages, json_mode: bool = False, metadata: Optional[Dict] = None):
    """Open the parent run for one llm_service.chat() call. Returns None if tracing is off.

    Runs are posted with a start time and later patched with an end time — previously runs
    were created once with outputs but no end_time, so LangSmith showed them 'pending' forever.
    """
    if not _initialized:
        return None
    try:
        from langsmith import RunTree
        run = RunTree(
            name=f"llm_call/{agent_name}",
            run_type="chain",
            inputs={"messages": messages, "json_mode": json_mode},
            project_name=settings.langsmith_project,
            extra={"metadata": {"agent": agent_name, **(metadata or {})}},
            tags=[f"agent:{agent_name}"],
            ls_client=_get_client(),
        )
        run.post()
        return run
    except Exception as e:
        logger.debug(f"LangSmith start_llm_trace failed (non-fatal): {e}")
        return None


def start_attempt(trace, provider: str, model: str, **params):
    """Open a child llm run for one provider/model attempt."""
    if trace is None:
        return None
    try:
        child = trace.create_child(
            name=f"{provider}/{model}",
            run_type="llm",
            inputs={"messages": trace.inputs.get("messages"), "model": model, "provider": provider, **params},
            extra={"metadata": {"ls_provider": provider, "ls_model_name": model, "provider": provider, "model": model}},
        )
        child.post()
        return child
    except Exception as e:
        logger.debug(f"LangSmith start_attempt failed (non-fatal): {e}")
        return None


def _usage_metadata(usage: Optional[Dict]) -> Dict[str, int]:
    usage = usage or {}
    return {
        "input_tokens": usage.get("prompt_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }


def end_attempt(attempt, output: Optional[str] = None, error: Optional[str] = None,
                usage: Optional[Dict] = None, latency_ms: Optional[float] = None,
                cooldown_s: Optional[float] = None):
    """Close an attempt run with its output or error."""
    if attempt is None:
        return
    try:
        metadata: Dict[str, Any] = {}
        if latency_ms is not None:
            metadata["latency_ms"] = round(latency_ms, 1)
        if cooldown_s:
            metadata["cooldown_s"] = round(cooldown_s)
        outputs = None
        if output is not None:
            outputs = {"response": output, "usage_metadata": _usage_metadata(usage)}
        attempt.end(outputs=outputs, error=error, metadata=metadata or None)
        attempt.patch()
    except Exception as e:
        logger.debug(f"LangSmith end_attempt failed (non-fatal): {e}")


def end_llm_trace(trace, output: Optional[str] = None, error: Optional[str] = None,
                  provider: Optional[str] = None, model: Optional[str] = None,
                  usage: Optional[Dict] = None, failed_attempts: int = 0, skipped=None):
    """Close the parent run — success with the winning model, or the failure summary."""
    if trace is None:
        return
    try:
        metadata: Dict[str, Any] = {"failed_attempts": failed_attempts, "skipped_models": skipped or []}
        if provider:
            metadata.update({"provider": provider, "model": model})
        outputs = {"response": output, "usage_metadata": _usage_metadata(usage)} if output is not None else None
        trace.end(outputs=outputs, error=error, metadata=metadata)
        trace.patch()
    except Exception as e:
        logger.debug(f"LangSmith end_llm_trace failed (non-fatal): {e}")


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
