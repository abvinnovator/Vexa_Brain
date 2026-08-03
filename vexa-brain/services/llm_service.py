from groq import AsyncGroq
from config import settings
from typing import List, Dict, Optional
from services import tracing_service
import httpx
import logging
import time
import asyncio
import json
import re

logger = logging.getLogger(__name__)

_groq_client: Optional[AsyncGroq] = None

# Free models from OpenRouter to fall back on if Groq tokens/rate-limits exhaust.
# Ordered with strict instruction-tuned & JSON-capable models first!
OPENROUTER_FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-small-24b-instruct-2501:free",
    "google/gemma-2-9b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
]


def get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


def _validate_json_mode(content: str) -> bool:
    """Ensure response contains a valid JSON object block."""
    if not content or not content.strip():
        return False
    start = content.find("{")
    end = content.rfind("}")
    return start != -1 and end != -1 and end > start


async def chat(
    messages: List[Dict[str, str]],
    temperature: float = None,
    max_tokens: int = None,
    json_mode: bool = False,
    agent_name: str = "unknown"
) -> str:
    """Send messages to LLM and return response text.

    Tries Groq LLM primary service first. If Groq rate-limits or exhausts tokens (429/errors),
    automatically falls back to OpenRouter free models in sequence so automation is never interrupted.
    """
    temp = temperature or settings.llm_temperature
    max_t = max_tokens or settings.llm_max_tokens

    # --- 1. Try Groq Primary ---
    try:
        groq_client = get_groq_client()
        kwargs = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_t,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        start_time = time.time()
        for attempt in range(1, 3):
            try:
                response = await groq_client.chat.completions.create(**kwargs)
                latency_ms = (time.time() - start_time) * 1000

                usage = tracing_service.extract_token_usage(response)
                content = response.choices[0].message.content

                if not content or not content.strip():
                    raise ValueError("Groq returned empty content.")

                if json_mode and not _validate_json_mode(content):
                    raise ValueError("Groq failed to output valid JSON object structure.")

                _log_to_langsmith(
                    agent_name=agent_name,
                    messages=messages,
                    response_text=content,
                    usage=usage,
                    latency_ms=latency_ms,
                    model=settings.llm_model,
                    provider="groq"
                )

                logger.info(f"LLM [Groq/{agent_name}]: {usage.get('total_tokens', '?')} tokens, {latency_ms:.0f}ms")
                return content
            except Exception as e:
                err_str = str(e).lower()
                if ("429" in err_str or "rate limit" in err_str or "quota" in err_str) and attempt < 2:
                    await asyncio.sleep(1.5)
                else:
                    raise e
    except Exception as groq_err:
        logger.warning(f"Groq LLM failed/exhausted ({groq_err}). Switching to OpenRouter fallback models...")

    # --- 2. OpenRouter Fallback Chain ---
    api_key = settings.open_router_api_key
    if not api_key:
        logger.error("No OpenRouter API key configured in settings!")
        raise Exception("LLM primary (Groq) failed and no OpenRouter API key available.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://vexa.app",
        "X-Title": "Vexa Brain",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for model_name in OPENROUTER_FREE_MODELS:
            start_time = time.time()
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_t
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                logger.info(f"Trying OpenRouter fallback model: {model_name}...")
                resp = await client.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    
                    if "choices" not in data or not data["choices"]:
                        raise ValueError(f"OpenRouter model {model_name} returned no choices: {data}")
                        
                    content = data["choices"][0]["message"].get("content")
                    
                    if not content or not content.strip():
                        raise ValueError(f"OpenRouter model {model_name} returned empty content.")

                    if json_mode and not _validate_json_mode(content):
                        raise ValueError(f"OpenRouter model {model_name} returned plain text instead of JSON.")
                        
                    latency_ms = (time.time() - start_time) * 1000
                    usage = data.get("usage", {})

                    _log_to_langsmith(
                        agent_name=agent_name,
                        messages=messages,
                        response_text=content,
                        usage=usage,
                        latency_ms=latency_ms,
                        model=model_name,
                        provider="openrouter"
                    )

                    logger.info(f"LLM [OpenRouter/{model_name}/{agent_name}]: Success! {latency_ms:.0f}ms")
                    return content
                else:
                    logger.warning(f"OpenRouter model {model_name} returned HTTP {resp.status_code}: {resp.text[:150]}")
            except Exception as or_err:
                logger.warning(f"OpenRouter model {model_name} validation error: {or_err}")
                continue

    raise Exception("All LLM providers (Groq primary and OpenRouter fallback chain) failed to return valid JSON.")


def _log_to_langsmith(
    agent_name: str,
    messages: List[Dict[str, str]],
    response_text: str,
    usage: Dict,
    latency_ms: float,
    model: str,
    provider: str
):
    if not tracing_service._initialized:
        return

    try:
        from langsmith import Client

        client = Client()
        client.create_run(
            name=f"llm/{provider}/{agent_name}",
            run_type="llm",
            inputs={
                "messages": messages,
                "model": model,
                "provider": provider
            },
            outputs={
                "response": response_text,
            },
            extra={
                "metadata": {
                    "agent": agent_name,
                    "model": model,
                    "provider": provider,
                    "latency_ms": round(latency_ms, 1),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "runtime": {"type": provider},
            },
            project_name=settings.langsmith_project,
        )
    except Exception as e:
        logger.debug(f"LangSmith trace failed (non-fatal): {e}")
