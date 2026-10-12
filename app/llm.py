"""Thin OpenAI-compatible chat clients: OpenRouter (primary, free models) and GLM (reserve)."""

import logging
from dataclasses import dataclass

import httpx

from .config import GLM_BASE_URL, OPENROUTER_BASE_URL, settings

log = logging.getLogger("leadorch.llm")


@dataclass
class ChatResult:
    content: str
    provider: str  # e.g. "openrouter:nvidia/..." or "glm:glm-4-flash"


def _openai_chat(base_url: str, api_key: str, model: str, system: str, user: str, provider_label: str) -> ChatResult:
    """Single chat completion call. Raises on any transport/HTTP error — retries live upstream."""
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 500,
        },
        timeout=settings.llm_timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    if not content:
        raise ValueError(f"empty completion from {provider_label}")
    return ChatResult(content=content, provider=f"{provider_label}:{model}")


def chat_openrouter(system: str, user: str) -> ChatResult:
    if not settings.openrouter_enabled:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return _openai_chat(
        OPENROUTER_BASE_URL, settings.openrouter_api_key, settings.openrouter_model,
        system, user, "openrouter",
    )


def chat_glm(system: str, user: str) -> ChatResult:
    if not settings.glm_enabled:
        raise RuntimeError("GLM_API_KEY is not set")
    return _openai_chat(
        GLM_BASE_URL, settings.glm_api_key, settings.glm_model,
        system, user, "glm",
    )
