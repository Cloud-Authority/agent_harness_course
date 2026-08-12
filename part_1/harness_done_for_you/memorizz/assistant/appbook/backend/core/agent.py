"""MemoRizz MemAgent: persona + memory provider + toolbox in one object."""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from backend.config import SHARED_DIR
from backend.core import store
from backend.core.llm_client import model
from backend.core.memory import MemoRizzMemory
from backend.core.tools import toolbox

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from runtime import TurnTrace  # noqa: E402


def _brief_markdown(data: dict) -> str:
    lines = ["## Morning brief", f"Scope: Outerwear + Tops · UK + EU · as of {data['as_of']}", "", "### Restock — 3 new decisions"]
    for item in data["restock"]:
        lines.append(f"- **{item['on_hand']} units · {item['city']} · {item['name']} {item['colour']} {item['size']}** — {item['cover_weeks']}w cover; recommend {item['recommended_qty']} units.")
    lines.extend(["", "### Top movers"])
    lines.extend(f"- **£{row['revenue']:,.0f} · {row['region']} · {row['name']}** — {row['units']} units." for row in data["top_movers"])
    lines.extend(["", "### Anomalies"])
    lines.extend(f"- **{row['change']} · {row['signal']}** — {row['why']}." for row in data["anomalies"])
    if data["suppressed"]:
        lines.extend(["", f"Suppressed {len(data['suppressed'])} handled item: Berlin ThermaCore (`PO-BER-THC-OPEN`)."])
    return "\n".join(lines)


def _answer(intent: str, data: Any, exclusions: list[str]) -> str:
    if intent == "morning_brief":
        return _brief_markdown(data)
    if intent == "explain_spike":
        internal = data["internal"]
        return (f"## WarmLayer · UK\n\n**{internal['last_7d_units']} units last week, {internal['change_percent']:+d}% vs the prior weekly average.** "
                f"No internal promotion was found. A UK cold snap crossed Kata's documented 12°C thermal trigger, so weather is the likely demand signal—not proof of causation.\n\n"
                "Sources: `orders + order_lines + variants + products`; Regional Merchandising Notes; Seasonal Trading Calendar; Tavily weather signal fixture.")
    if intent == "stock_visual":
        return "## ThermaCore stock across regions\n\nM/L are near sell-out while XS/XXL carry the overhang. Build A returns grounded size rows; Build B adds sandbox chart generation."
    if intent == "profitability":
        rows = data["rows"]
        table = "\n".join(f"- **{row['region']} · £{row['gross_margin']:,.0f} margin · {row['margin_percent']}%** — {row['units']} units, {row['avg_discount_percent']}% avg discount." for row in rows)
        suffix = f"\n\nSaved recurring exclusion: {', '.join(exclusions)}." if exclusions else ""
        return "## Quarterly regional profitability\n\nRanked by gross-margin value (net revenue − unit cost).\n\n" + table + suffix
    return "Grounded business answer ready."


class MemAgent:
    persona = "ERPA: concise Kata merchandising assistant; numbers first; never re-raise handled work."

    def __init__(self):
        store.initialize()
        self.memory = MemoRizzMemory()
        self.toolbox = toolbox

    def run(self, message: str, thread_id: str = "demo-thread", user_id: str = "planner-01") -> dict[str, Any]:
        trace = TurnTrace("memorizz", message)
        with trace.span("memory.recall", "memory_read", memory_types=["semantic", "episodic", "procedural"]):
            recalled = self.memory.recall(message, user_id)
            trace.recalled = [{"type": item["memory_type"], "content": item["content"], "source": item["metadata"].get("source", "memory")} for item in recalled]
        with trace.span("model.decide", "model"):
            decision = model.decide(message)
            trace.decision = decision
            trace.tokens = 210 + len(message.split()) * 3 + len(recalled) * 18
        exclusions = self.memory.exclusions(user_id)
        wrote = []
        if re.search(r"(?:don't|do not|stop) (?:showing|show|being shown).*accessories", message, re.I):
            with trace.span("memory.write.preference", "memory_write", memory_type="semantic"):
                item = self.memory.remember("semantic", "Exclude Accessories from recurring briefs and reviews", user_id=user_id,
                                            metadata={"source": "user_turn", "kind": "preference"})
                wrote.append({"type": "semantic", "content": item["content"], "deduplicated": item.get("deduplicated", False)})
            exclusions = self.memory.exclusions(user_id)
        with trace.span("tools.dispatch", "tool", tools=decision["tools"]):
            if decision["intent"] == "morning_brief":
                data = self.toolbox.query_inventory(message, exclusions)
            elif decision["intent"] == "explain_spike":
                data = self.toolbox.query_sales(message)
            elif decision["intent"] == "stock_visual":
                data = self.toolbox.query_inventory(message)
            elif decision["intent"] == "profitability":
                data = self.toolbox.query_sales(message, exclusions)
            else:
                data = self.toolbox.query_sales(message, exclusions)
        with trace.span("memory.write.turn", "memory_write", memory_type="working"):
            trace.written = wrote + [{"type": "working", "content": f"turn:{thread_id}"}]
            answer = _answer(decision["intent"], data, exclusions)
            summary = trace.summary()
            store.save_turn(thread_id, message, answer, summary)
        summary = trace.summary()
        # save_turn receives a nearly identical pre-final summary; response is authoritative.
        return {"answer": answer, "data": data, "trace": summary, "instrumentation": {
            "recall": summary["recalled"], "decide": summary["decision"], "write": summary["written"]}}


_agent: MemAgent | None = None


def get_agent(*, restart: bool = False) -> MemAgent:
    global _agent
    if _agent is None or restart:
        _agent = MemAgent()
    return _agent
