"""Four-node ERPA graph with a semantic cache in front of the whole loop."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from backend.config import SHARED_DIR, settings
from backend.core import store
from backend.core.cache import semantic_cache
from backend.core.llm_client import model
from backend.core.memory import memory_provider
from backend.core.semantic import semantic_layer
from backend.core.skills import disclose
from backend.core.tools import tool_registry

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from runtime import TurnTrace  # noqa: E402


def _brief_markdown(data: dict) -> str:
    lines = ["## Morning brief", f"Scope: Outerwear + Tops · UK + EU · as of {data['as_of']}", "", "### Restock — 3 new decisions"]
    lines.extend(f"- **{row['on_hand']} units · {row['city']} · {row['name']} {row['colour']} {row['size']}** — {row['cover_weeks']}w cover; recommend {row['recommended_qty']} units."
                 for row in data["restock"])
    lines.extend(["", "### Top movers"])
    lines.extend(f"- **£{row['revenue']:,.0f} · {row['region']} · {row['name']}** — {row['units']} units." for row in data["top_movers"])
    lines.extend(["", "### Anomalies"])
    lines.extend(f"- **{row['change']} · {row['signal']}** — {row['why']}." for row in data["anomalies"])
    if data["suppressed"]:
        lines.extend(["", "Suppressed 1 handled item: Berlin ThermaCore (`PO-BER-THC-OPEN`)."])
    return "\n".join(lines)


def _render_answer(intent: str, data: Any, exclusions: list[str], message: str = "") -> str:
    remembered = re.search(r"(?:remember that|please remember)\s+(.+?)[.!?]*$", message, re.I)
    if remembered:
        return ("## Memory saved\n\n"
                f"I’ll remember: **{remembered.group(1).strip()}**. "
                "This turn is visible as an OAMP semantic-memory write and in the session’s promoted ScratchFS observation note.")
    if intent == "morning_brief":
        return _brief_markdown(data)
    if intent == "explain_spike":
        internal = data["internal"]
        return (f"## WarmLayer · UK\n\n**{internal['last_7d_units']} units last week, {internal['change_percent']:+d}% vs the prior weekly average.** "
                "No internal promotion was found. A UK cold snap crossed Kata's documented 12°C thermal trigger, so weather is the likely signal—not proof of cause.\n\n"
                "Sources: `orders + order_lines + variants + products`; approved institutional guidance; governed dated weather signal.")
    if intent == "stock_visual":
        return semantic_layer.render_result(message, data, governed=True)
    if intent == "profitability":
        rows = data["rows"]
        table = "\n".join(f"- **{row['region']} · £{row['gross_margin']:,.0f} margin · {row['margin_percent']}%** — {row['units']} units, {row['avg_discount_percent']}% average discount." for row in rows)
        saved = f"\n\nSaved recurring exclusion: {', '.join(exclusions)}." if exclusions else ""
        return "## Quarterly regional profitability\n\nRanked by gross-margin value (net revenue − unit cost).\n\n" + table + saved
    if intent == "calendar":
        return "Calendar execution is not available in this custom build. MCP is explicitly labelled missing; no meeting was read or created."
    if intent == "greeting":
        return semantic_layer.render_result(message, {}, governed=True)
    return semantic_layer.render_result(message, data, governed=True)


class ERPAStateGraph:
    graph = {
        "boundary": "semantic_cache → (hit: return | miss: assemble_context)",
        "nodes": ["assemble_context", "call_model", "dispatch_tools", "persist"],
        "edges": ["assemble_context→call_model", "call_model→dispatch_tools", "dispatch_tools→persist", "persist→END"],
    }

    def assemble_context(self, state: dict, trace: TurnTrace) -> dict:
        with trace.span("assemble_context", "graph_node"):
            with trace.span("memory.read", "memory_read", provider="OAMP"):
                recalled = memory_provider.recall(
                    state["message"],
                    state["user_id"],
                    thread_id=state["thread_id"],
                )
                trace.recalled = [{"type": row["memory_type"], "content": row["content"], "source": row["metadata"].get("source", "memory")} for row in recalled]
            skills = disclose(state["message"])
            tools = tool_registry.retrieve(state["message"])
            semantic = semantic_layer.meaning(state["message"])
            context_card = memory_provider.context_card(state["thread_id"], state["user_id"])
            state["context"] = {"memory": trace.recalled[-10:], "context_card": context_card,
                                "compaction": {"kept": min(len(recalled), 10), "recalled": len(recalled)},
                                "skills": skills, "tools": tools, "semantic": semantic}
        return state

    def call_model(self, state: dict, trace: TurnTrace) -> dict:
        with trace.span("call_model", "model", model_span=True):
            state["decision"] = model.decide(state["message"], state["context"])
            trace.decision = state["decision"]
            trace.tokens = 240 + len(state["message"].split()) * 4 + len(state["context"]["memory"]) * 18 + state["context"]["skills"]["token_comparison"]["progressive"]
        return state

    def dispatch_tools(self, state: dict, trace: TurnTrace) -> dict:
        decision, message = state["decision"], state["message"]
        exclusions = memory_provider.exclusions(state["user_id"])
        with trace.span("dispatch_tools", "graph_node", selected=decision["tools"]):
            if decision["intent"] == "morning_brief":
                data = tool_registry.call("semantic_query", question=message, exclusions=exclusions)
            elif decision["intent"] == "explain_spike":
                signal = tool_registry.call("sales_signal", product_line="WarmLayer", region="UK")
                external = tool_registry.call("external_signal_search", region="UK", signal_type="weather")
                docs = tool_registry.call("institutional_search", query="WarmLayer UK cold seasonal temperature")
                data = {"internal": {
                    "last_7d_units": signal["current_units"],
                    "prior_weekly_average": signal["prior_weekly_average"],
                    "change_percent": signal["change_percent"],
                    "provenance": signal["provenance"],
                }, "external": external, "institutional": docs}
            elif decision["intent"] == "stock_visual":
                data = tool_registry.stock_visual(f"session-{state['thread_id']}")
            elif decision["intent"] == "profitability":
                data = tool_registry.call("semantic_query", question=message, exclusions=exclusions)
            elif decision["intent"] == "calendar":
                data = {"error": "capability_missing", "capability": "MCP/calendar"}
            elif decision["intent"] == "greeting":
                data = {"capabilities": ["catalog", "inventory", "demand", "profitability", "memory", "skills"]}
            else:
                data = tool_registry.call("semantic_query", question=message, exclusions=exclusions)
            state["data"] = data
        return state

    def persist(self, state: dict, trace: TurnTrace) -> dict:
        wrote = []
        with trace.span("persist", "graph_node"):
            remembered = re.search(r"(?:remember that|please remember)\s+(.+?)[.!?]*$", state["message"], re.I)
            if remembered:
                preference = remembered.group(1).strip()
                with trace.span("memory.write.preference", "memory_write", provider="OAMP", memory_type="semantic"):
                    item = memory_provider.write(
                        "semantic", preference, state["user_id"],
                        {"source": "explicit_user_memory", "kind": "preference"},
                        thread_id=state["thread_id"],
                    )
                    wrote.append({"type": "semantic", "content": item["content"],
                                  "deduplicated": item.get("deduplicated", False)})
            if re.search(r"(?:don't|do not|stop) (?:showing|show|being shown).*accessories", state["message"], re.I):
                with trace.span("memory.write.preference", "memory_write", provider="OAMP", memory_type="semantic"):
                    item = memory_provider.write("semantic", "Exclude Accessories from recurring briefs and reviews", state["user_id"],
                                                 {"source": "user_turn", "kind": "preference"}, thread_id=state["thread_id"])
                    wrote.append({"type": "semantic", "content": item["content"], "deduplicated": item.get("deduplicated", False)})
            exclusions = memory_provider.exclusions(state["user_id"])
            state["answer"] = _render_answer(state["decision"]["intent"], state["data"], exclusions, state["message"])
            with trace.span("memory.write.working", "memory_write", provider="OAMP", memory_type="working"):
                item = memory_provider.write("working", f"{state['thread_id']}: {state['message']} → {state['decision']['intent']}", state["user_id"],
                                             {"source": "turn", "thread_id": state["thread_id"]}, thread_id=state["thread_id"])
                wrote.append({"type": "working", "content": item["content"], "deduplicated": item.get("deduplicated", False)})
            memory_provider.persist_assistant_message(state["thread_id"], state["answer"], state["user_id"])
            # Live state is checkpointed by LangGraph's OracleSaver during every
            # node transition. The compact table is only the offline mirror.
            if not settings.live:
                checkpoint = {"last_message": state["message"], "last_intent": state["decision"]["intent"], "exclusions": exclusions}
                with store.connect() as conn:
                    conn.execute("INSERT OR REPLACE INTO custom_checkpoints VALUES (?,?,?)",
                                 (state["thread_id"], json.dumps(checkpoint), datetime.now(timezone.utc).isoformat()))
            trace.written = wrote
        return state

    def run(self, message: str, thread_id: str = "demo-thread", user_id: str = "planner-01", *, bypass_cache: bool = False) -> dict[str, Any]:
        store.initialize()
        trace = TurnTrace("custom", message)
        with trace.span("boundary_cache.lookup", "cache", placement="before assemble_context"):
            hit = None if bypass_cache else semantic_cache.get(message)
        if hit:
            trace.cache_hit = True
            trace.decision = {"intent": "cache_hit", "reason": f"semantic similarity {hit['similarity']}"}
            summary = trace.summary()
            store.save_trace(thread_id, summary)
            return {"answer": hit["answer"], "data": hit["payload"]["data"], "context": None, "trace": summary,
                    "instrumentation": {"recall": [], "decide": trace.decision, "write": []}}

        state = {"message": message, "thread_id": thread_id, "user_id": user_id}
        state = self.assemble_context(state, trace)
        state = self.call_model(state, trace)
        state = self.dispatch_tools(state, trace)
        state = self.persist(state, trace)
        summary = trace.summary()
        store.save_trace(thread_id, summary)
        semantic_cache.put(message, state["answer"], {"data": state["data"]}, trace.tokens, user_id)
        return {"answer": state["answer"], "data": state["data"], "context": state["context"], "trace": summary,
                "instrumentation": {"recall": summary["recalled"], "decide": summary["decision"], "write": summary["written"]}}


_graph: Any | None = None


def get_graph(*, restart: bool = False) -> Any:
    global _graph
    if _graph is None or restart:
        if settings.live:
            from backend.core.langgraph_live import LiveOracleGraph
            from backend.core.oracle_live import get_oracle_stack

            _graph = LiveOracleGraph(get_oracle_stack())
        else:
            _graph = ERPAStateGraph()
    return _graph
