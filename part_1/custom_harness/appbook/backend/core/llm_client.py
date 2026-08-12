"""Swappable model boundary. Deterministic local mode keeps every stage runnable."""
from __future__ import annotations

import json
import time
from typing import Literal

from backend.config import settings


class ChatDecisionModel:
    def decide(self, message: str, context: dict) -> dict:
        time.sleep(0.009)
        text = message.lower()
        if text.strip(" .!?") in {"hi", "hello", "hey", "hi there", "hello there", "good morning", "good afternoon"}:
            return {"intent": "greeting", "tools": [], "reason": "respond conversationally and explain the available catalog capabilities"}
        if "morning brief" in text:
            return {"intent": "morning_brief", "tools": ["semantic_query"], "reason": "compose an attention list using recalled policy and actions"}
        if "warmlayer" in text and any(term in text for term in ("spike", "trend", "demand", "selling")):
            return {"intent": "explain_spike", "tools": ["sales_signal", "institutional_search", "external_signal_search"], "reason": "triangulate three governed source types"}
        if "thermacore" in text:
            return {"intent": "stock_visual", "tools": ["inventory_status", "sandbox_python"], "reason": "render regional stock and size curve"}
        if "profit" in text or "margin" in text:
            return {"intent": "profitability", "tools": ["regional_profitability"], "reason": "use canonical gross-margin definition"}
        if "calendar" in text or "schedule" in text or "book" in text:
            return {"intent": "calendar", "tools": [], "reason": "calendar/MCP is explicitly missing from this build"}
        return {"intent": "business_question", "tools": ["morning_brief_inputs"], "reason": "ground in the semantic layer"}


class LiveChatDecisionModel:
    """Use Claude Opus 4.8 adaptive thinking for the live decision boundary."""

    def __init__(self) -> None:
        from langchain_anthropic import ChatAnthropic
        from pydantic import BaseModel, Field

        class Decision(BaseModel):
            intent: Literal[
                "morning_brief", "explain_spike", "stock_visual",
                "profitability", "calendar", "business_question", "greeting",
            ]
            tools: list[str] = Field(description="Smallest relevant subset of available tool names")
            reason: str

        self._model = ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
            thinking={"type": settings.anthropic_thinking},
        ).with_structured_output(Decision)

    def decide(self, message: str, context: dict) -> dict:
        decision = self._model.invoke([
            (
                "system",
                "You route a Kata merchandising assistant. Use only tools present in the supplied context. "
                "Prefer the smallest tool set; ground business claims in semantic_query. "
                "Use morning_brief for that exact task, explain_spike for demand-spike diagnosis, "
                "stock_visual for visual stock requests, profitability for profit/margin questions, "
                "and calendar for scheduling or availability.",
            ),
            ("human", f"Request:\n{message}\n\nAvailable context:\n{json.dumps(context, default=str)}"),
        ])
        return decision.model_dump()


# The live application uses the full tool-calling graph in ``langgraph_live.py``.
# This deterministic decision model exists only for the zero-credential mirror.
model = ChatDecisionModel()
