"""One OpenAI Responses API boundary for the Total Recall appbook."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI, OpenAI

from ..config import settings


MODEL = settings.model
MAX_OUTPUT_TOKENS = settings.max_output_tokens
_key = settings.openai_api_key or "OPENAI_API_KEY_NOT_SET"
client = OpenAI(api_key=_key, timeout=120.0, max_retries=2)
async_client = AsyncOpenAI(api_key=_key, timeout=120.0, max_retries=2)


def request_options(**overrides: Any) -> dict[str, Any]:
    """Return the one shared, stateless GPT-5.5 request policy."""
    options: dict[str, Any] = {
        "model": MODEL,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": settings.reasoning_effort},
        "store": False,
    }
    options.update(overrides)
    return options


def response_text(response: Any) -> str:
    return str(getattr(response, "output_text", "") or "")


def function_calls(response: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "function_call":
            continue
        try:
            arguments = json.loads(item.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
        calls.append(
            {
                "name": item.name,
                "arguments": arguments,
                "call_id": item.call_id,
            }
        )
    return calls


def response_items(response: Any) -> list[Any]:
    """Keep every output item needed by the next Tool-continuation request."""
    return list(getattr(response, "output", []) or [])
