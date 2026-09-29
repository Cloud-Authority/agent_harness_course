"""The model boundary: Claude when a key is present, the scripted responder otherwise.

Both sit behind the same call: a frozen system prompt, a fixed tool list and
an append-only message history go in, one AI message comes out. Thinking
blocks are bound to that exact prefix, so nothing earlier in a conversation is
ever rewritten.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from backend.config import settings
from backend.core import scripted, tools

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_model: Any | None = None


def claude_label() -> str:
    return f"Claude {settings.anthropic_model}"


def default_responder() -> str:
    return "claude" if settings.claude_available else "scripted"


def label(kind: str) -> str:
    return claude_label() if kind == "claude" else scripted.LABEL


def _claude() -> Any:
    """ChatAnthropic with adaptive thinking, the tool list bound once, tool choice left automatic."""
    global _model
    if _model is None:
        from langchain_anthropic import ChatAnthropic

        _model = ChatAnthropic(
            model=settings.anthropic_model, api_key=settings.anthropic_api_key, max_tokens=16000,
            thinking={"type": "adaptive"}, output_config={"effort": settings.effort},
            betas=[FALLBACK_BETA], model_kwargs={"fallbacks": "default"},
            timeout=settings.model_timeout_seconds, max_retries=2,
        ).bind_tools(tools.schemas())
    return _model


def _without_thinking(messages: list[Any]) -> list[Any]:
    """Recovery only: a copy of the history with thinking blocks removed."""
    cleaned = []
    for message in messages:
        if isinstance(message, AIMessage) and isinstance(message.content, list):
            kept = [block for block in message.content if not (
                isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"})]
            message = message.model_copy(update={"content": kept or ""})
        cleaned.append(message)
    return cleaned


async def respond(kind: str, system_prompt: str, messages: list[Any]) -> tuple[AIMessage, dict[str, Any]]:
    """One model call. Returns the AI message and notes for the trace."""
    if kind != "claude":
        return scripted.respond(messages), {"responder": scripted.LABEL}
    from anthropic import BadRequestError

    notes: dict[str, Any] = {"responder": claude_label(), "effort": settings.effort,
                             "thinking": "adaptive"}
    prompt = [SystemMessage(content=system_prompt)]
    try:
        response = await _claude().ainvoke(prompt + messages, cache_control={"type": "ephemeral"})
    except BadRequestError as exc:
        if "thinking" not in str(exc).lower():
            raise
        # The history was changed outside this conversation. Drop its thinking once and go on.
        notes["recovered"] = "thinking blocks dropped after a prefix mismatch"
        response = await _claude().ainvoke(prompt + _without_thinking(messages),
                                           cache_control={"type": "ephemeral"})
    served_by = response.response_metadata.get("model_name") or response.response_metadata.get("model")
    if served_by and served_by != settings.anthropic_model:
        notes["served_by"] = served_by
    return response, notes


def text_of(message: AIMessage) -> str:
    """The user-facing text of an AI message, without thinking or tool blocks."""
    if isinstance(message.content, str):
        return message.content.strip()
    return "\n".join(block.get("text", "") for block in message.content
                     if isinstance(block, dict) and block.get("type") == "text").strip()


def usage_of(message: AIMessage) -> dict[str, int]:
    usage = message.usage_metadata or {}
    details = usage.get("input_token_details") or {}
    return {"input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "cache_read_tokens": int(details.get("cache_read", 0) or 0),
            "cache_write_tokens": int(details.get("cache_creation", 0) or 0)}


def status() -> dict[str, Any]:
    kind = default_responder()
    return {"responder": kind, "label": label(kind), "claude_available": settings.claude_available,
            "key_present": bool(settings.anthropic_api_key), "forced": settings.responder,
            "model": settings.anthropic_model if kind == "claude" else None,
            "configuration": {"thinking": "adaptive", "effort": settings.effort, "max_tokens": 16000,
                              "tool_choice": "automatic", "fallbacks": "default",
                              "prompt_cache": "top-level ephemeral breakpoint"} if kind == "claude" else None,
            "note": "Text the assistant reads is sent to Anthropic." if kind == "claude"
            else "No model is called."}
