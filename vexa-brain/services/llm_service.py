from groq import AsyncGroq
from config import settings
from typing import List, Dict, Optional, Tuple
from services import tracing_service
import httpx
import logging
import time
import json

logger = logging.getLogger(__name__)

_groq_client: Optional[AsyncGroq] = None

# Groq models this account can actually use (checked against /openai/v1/models).
# llama-3.3-70b / llama-3.1-8b / compound-mini return 404 and gemma2-9b-it is decommissioned.
# Ordered fastest/cheapest first: qwen answers an interactive step in ~1.7s with ~90 output tokens.
GROQ_FALLBACK_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# Extra request params per model. gpt-oss models spend max_tokens on hidden reasoning at the
# default effort and then fail JSON mode (Groq returns 400 json_validate_failed) — keep it low.
GROQ_MODEL_PARAMS = {
    "openai/gpt-oss-120b": {"reasoning_effort": "low"},
    "openai/gpt-oss-20b": {"reasoning_effort": "low"},
}

# Free models from OpenRouter, used only when every Groq model is unavailable.
# Free tier is capped (50 requests/day, ~20/min), so failed attempts are expensive — see cooldowns.
# Slugs verified against https://openrouter.ai/api/v1/models on 2026-10-01.
OPENROUTER_FREE_MODELS = [
    "qwen/qwen3.8-27b:free",
    "poolside/laguna-s-2.1:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "cohere/north-mini-code:free",
    "poolside/laguna-xs-2.1:free",
    "openrouter/free"
]

# Per-attempt timeout. A healthy call finishes in 1-7s; waiting 30s on a stuck model is what
# made automations crawl.
REQUEST_TIMEOUT_S = 15.0
# Stop walking the fallback chain after this long so the app gets an error instead of hanging.
TOTAL_BUDGET_S = 45.0
# Max OpenRouter attempts per call — every failed attempt burns the free daily quota.
MAX_OPENROUTER_ATTEMPTS = 4

# Cooldowns: a model that just failed is skipped on subsequent calls instead of being retried
# (and burning rate limit) every single time.
COOLDOWN_MODEL_GONE_S = 6 * 3600   # 404 / decommissioned / no access
COOLDOWN_RATE_LIMIT_S = 60         # 429 without a usable Retry-After
COOLDOWN_SERVER_ERROR_S = 30       # 5xx / timeout / network
COOLDOWN_AUTH_S = 3600             # 401 / 403 — key problem, affects the whole provider

_cooldowns: Dict[str, float] = {}  # "provider:model" or "provider:*" -> unix time when usable again


class LLMAttemptError(Exception):
    """A single provider/model attempt failed. `cooldown_s` = how long to skip this model."""

    def __init__(self, message: str, cooldown_s: float = 0, provider_wide: bool = False):
        super().__init__(message)
        self.cooldown_s = cooldown_s
        self.provider_wide = provider_wide


_openrouter_client: Optional[httpx.AsyncClient] = None


def get_openrouter_client() -> httpx.AsyncClient:
    """Shared client — creating an AsyncClient (TLS setup) costs ~0.1-0.7s, which used to be
    paid on every LLM call even when OpenRouter was never reached."""
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = httpx.AsyncClient()
    return _openrouter_client


def get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        # max_retries=0: the SDK's built-in retry/backoff on 429 adds seconds per model and
        # hides failures from our fallback logic.
        _groq_client = AsyncGroq(api_key=settings.groq_api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    return _groq_client


def _clean_json_content(content: str) -> str:
    """Extract clean JSON string from content, stripping markdown code fences if present."""
    if not content:
        return ""
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end+1].strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    return text


def _validate_json_mode(content: str) -> bool:
    """Ensure response contains a valid parseable JSON object."""
    cleaned = _clean_json_content(content)
    if not cleaned:
        return False
    try:
        json.loads(cleaned)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cooldown bookkeeping
# ---------------------------------------------------------------------------

def _cooldown_remaining(provider: str, model: str) -> float:
    now = time.time()
    until = max(_cooldowns.get(f"{provider}:{model}", 0), _cooldowns.get(f"{provider}:*", 0))
    return max(0.0, until - now)


def _set_cooldown(provider: str, model: str, err: LLMAttemptError):
    if err.cooldown_s <= 0:
        return
    key = f"{provider}:*" if err.provider_wide else f"{provider}:{model}"
    _cooldowns[key] = time.time() + err.cooldown_s
    logger.info(f"Cooling down {key} for {err.cooldown_s:.0f}s")


def _retry_after_s(headers) -> Optional[float]:
    try:
        value = headers.get("retry-after") if headers is not None else None
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def _classify_http_error(status: Optional[int], body: str, headers=None) -> Tuple[float, bool]:
    """Map an HTTP failure to (cooldown_seconds, provider_wide)."""
    text = (body or "").lower()
    if status in (401, 403):
        return COOLDOWN_AUTH_S, True
    if status == 404 or "decommissioned" in text or "model_not_found" in text or "does not exist" in text:
        return COOLDOWN_MODEL_GONE_S, False
    if status == 429:
        return _retry_after_s(headers) or COOLDOWN_RATE_LIMIT_S, False
    if status is None or status >= 500:
        return COOLDOWN_SERVER_ERROR_S, False
    # Other 4xx (e.g. 400 json_validate_failed) are about this request's output, not the model's
    # availability — don't cool down.
    return 0, False


def _candidates() -> List[Tuple[str, str]]:
    """Ordered (provider, model) chain, de-duplicated, configured model first."""
    chain: List[Tuple[str, str]] = []
    for m in [settings.llm_model] + GROQ_FALLBACK_MODELS:
        if m and ("groq", m) not in chain:
            chain.append(("groq", m))
    if settings.open_router_api_key:
        chain.extend(("openrouter", m) for m in OPENROUTER_FREE_MODELS)
    return chain


# ---------------------------------------------------------------------------
# Provider calls — each returns (content, usage) or raises LLMAttemptError
# ---------------------------------------------------------------------------

def _check_content(content: Optional[str], json_mode: bool, label: str) -> str:
    if not content or not content.strip():
        raise LLMAttemptError(f"{label} returned empty content")
    if json_mode:
        if not _validate_json_mode(content):
            raise LLMAttemptError(f"{label} returned invalid JSON")
        content = _clean_json_content(content)
    return content


async def _call_groq(model: str, messages, temp, max_t, json_mode, timeout_s) -> Tuple[str, Dict]:
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_t,
        "timeout": timeout_s,
        **GROQ_MODEL_PARAMS.get(model, {}),
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        response = await get_groq_client().chat.completions.create(**kwargs)
    except Exception as e:
        status = getattr(e, "status_code", None)
        headers = getattr(getattr(e, "response", None), "headers", None)
        cooldown, wide = _classify_http_error(status, str(e), headers)
        raise LLMAttemptError(f"Groq {model} HTTP {status}: {str(e)[:200]}", cooldown, wide) from e

    content = _check_content(response.choices[0].message.content, json_mode, f"Groq {model}")
    return content, tracing_service.extract_token_usage(response)


async def _call_openrouter(client: httpx.AsyncClient, model: str, messages, temp, max_t, json_mode, timeout_s) -> Tuple[str, Dict]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_t,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {settings.open_router_api_key}",
        "HTTP-Referer": "https://vexa.app",
        "X-Title": "Vexa Brain",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=timeout_s)
    except httpx.HTTPError as e:
        raise LLMAttemptError(f"OpenRouter {model} network error: {type(e).__name__}: {e}", COOLDOWN_SERVER_ERROR_S) from e

    if resp.status_code != 200:
        body = resp.text[:300]
        cooldown, wide = _classify_http_error(resp.status_code, body, resp.headers)
        # Free-tier daily cap: every free model will 429 until the quota resets — stop trying them all.
        if resp.status_code == 429 and "free-models-per-day" in body.lower():
            cooldown, wide = max(cooldown, 3600), True
        raise LLMAttemptError(f"OpenRouter {model} HTTP {resp.status_code}: {body}", cooldown, wide)

    data = resp.json()
    if "choices" not in data or not data["choices"]:
        # OpenRouter sometimes wraps upstream errors in a 200 body
        raise LLMAttemptError(f"OpenRouter {model} returned no choices: {str(data)[:200]}", COOLDOWN_SERVER_ERROR_S)
    content = _check_content(data["choices"][0]["message"].get("content"), json_mode, f"OpenRouter {model}")
    return content, data.get("usage", {}) or {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def chat(
    messages: List[Dict[str, str]],
    temperature: float = None,
    max_tokens: int = None,
    json_mode: bool = False,
    agent_name: str = "unknown",
    metadata: Optional[Dict] = None,
    prefer_models: Optional[List[str]] = None
) -> str:
    """Send messages to LLM and return response text.

    Walks Groq models, then OpenRouter free models, skipping any model that is cooling down
    after a recent failure. Every attempt — success or failure — is traced to LangSmith as a
    child of one `llm_call/<agent>` run. `metadata` is attached to that run (e.g. automation ids).
    """
    temp = temperature if temperature is not None else settings.llm_temperature
    max_t = max_tokens or settings.llm_max_tokens

    # Groq rejects response_format=json_object with a 400 unless "json" appears in the messages,
    # which would fail every Groq model and fall through to the scarce OpenRouter quota.
    if json_mode and not any("json" in str(m.get("content", "")).lower() for m in messages):
        messages = [{"role": "system", "content": "Respond with a valid JSON object only."}] + list(messages)

    trace =tracing_service.start_llm_trace(agent_name, messages, json_mode=json_mode)
    started = time.time()
    errors: List[str] = []
    skipped: List[str] = []
    openrouter_attempts = 0

    chain = _candidates()
    if prefer_models:
        # Caller-preferred Groq models first (e.g. gpt-oss-120b writes better Telugu), then the usual chain
        preferred = [("groq", m) for m in prefer_models]
        chain = preferred + [pm for pm in chain if pm not in preferred]
    # If every model is cooling down, still try the one that recovers soonest rather than
    # failing outright without a single request.
    force_try = None
    if chain and all(_cooldown_remaining(p, m) > 0 for p, m in chain):
        force_try = min(chain, key=lambda pm: _cooldown_remaining(*pm))
        chain = [force_try]

    for provider, model in chain:
        label = f"{provider}/{model}"
        remaining = _cooldown_remaining(provider, model)
        if remaining > 0 and (provider, model) != force_try:
            skipped.append(f"{label} (cooldown {remaining:.0f}s)")
            continue

        budget_left = TOTAL_BUDGET_S - (time.time() - started)
        if budget_left <= 1:
            errors.append(f"time budget of {TOTAL_BUDGET_S:.0f}s exhausted")
            break
        if provider == "openrouter":
            if openrouter_attempts >= MAX_OPENROUTER_ATTEMPTS:
                errors.append(f"OpenRouter attempt cap ({MAX_OPENROUTER_ATTEMPTS}) reached")
                break
            openrouter_attempts += 1

        timeout_s = min(REQUEST_TIMEOUT_S, budget_left)
        attempt = tracing_service.start_attempt(trace, provider, model, temperature=temp, max_tokens=max_t)
        attempt_start = time.time()
        try:
            if provider == "groq":
                content, usage = await _call_groq(model, messages, temp, max_t, json_mode, timeout_s)
            else:
                content, usage = await _call_openrouter(get_openrouter_client(), model, messages, temp, max_t, json_mode, timeout_s)
        except LLMAttemptError as e:
            logger.warning(f"LLM [{label}/{agent_name}] failed: {e}")
            _set_cooldown(provider, model, e)
            tracing_service.end_attempt(attempt, error=str(e), cooldown_s=e.cooldown_s)
            errors.append(str(e))
            continue
        except Exception as e:  # unexpected bug — record it and keep falling back
            logger.exception(f"LLM [{label}/{agent_name}] unexpected error")
            tracing_service.end_attempt(attempt, error=f"{type(e).__name__}: {e}")
            errors.append(f"{label}: {type(e).__name__}: {e}")
            continue

        latency_ms = (time.time() - attempt_start) * 1000
        tracing_service.end_attempt(attempt, output=content, usage=usage, latency_ms=latency_ms)
        tracing_service.end_llm_trace(trace, output=content, provider=provider, model=model,
                                      usage=usage, failed_attempts=len(errors), skipped=skipped)
        logger.info(f"LLM [{label}/{agent_name}]: Success! {usage.get('total_tokens', '?')} tokens, "
                    f"{latency_ms:.0f}ms ({len(errors)} failed, {len(skipped)} skipped before)")
        return content

    summary = "; ".join(errors[-5:]) or "no models attempted"
    tracing_service.end_llm_trace(trace, error=summary, failed_attempts=len(errors), skipped=skipped)
    logger.error(f"LLM [{agent_name}] all providers failed after {time.time() - started:.1f}s: {summary}")
    raise Exception(
        "All LLM providers (Groq primary/fallbacks and OpenRouter fallback chain) failed to return valid response. "
        f"Last errors: {summary}"
    )
