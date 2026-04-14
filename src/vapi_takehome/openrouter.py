"""OpenRouter client wrapper.

Single entrypoint: complete_json() — calls OpenRouter with a model,
system prompt, and user messages; expects and validates JSON response.
"""

import json
from typing import Any

from openai import OpenAI

from vapi_takehome.config import settings
from vapi_takehome.logging_config import get_logger

logger = get_logger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
    return _client


def complete_json(
    system: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Call OpenRouter and return a parsed JSON dict.

    Raises ValueError on JSON parse failure (caller should log and handle).
    """
    model = model or settings.model_judge
    client = _get_client()

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, *messages],
    )
    raw = resp.choices[0].message.content
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed. model={model} raw={raw[:300]!r}")
        raise ValueError(f"OpenRouter did not return valid JSON: {e}") from e


def complete_text(
    system: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.7,
) -> str:
    """Call OpenRouter and return raw text completion."""
    model = model or settings.model_mutator
    client = _get_client()

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[{"role": "system", "content": system}, *messages],
    )
    return resp.choices[0].message.content or ""
