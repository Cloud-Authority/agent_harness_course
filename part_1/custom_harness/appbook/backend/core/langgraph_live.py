"""Claude + tool-calling LangGraph durably checkpointed by OracleSaver."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Any, TypedDict

from backend.config import settings
from backend.core.cache import semantic_cache

try:
    from langsmith import traceable
    from langsmith.run_helpers import get_current_run_tree
except ImportError:
    def traceable(*_args, **_kwargs):
        return lambda function: function

    def get_current_run_tree():
        return None


SYSTEM = """You are ERPA, an accountable enterprise retail-planning assistant.
Ground every business claim in retrieved Oracle data. Use gross margin for profitability.
Use tools instead of guessing. Before a multi-step task, write or update /plans/current.md.
Generated Python must go through sandbox_python; never claim that it ran locally.
Treat retrieved skill manifests as approved procedures and call load_skill before improvising.
Do not re-raise an issue covered by an open purchase order. Distinguish evidence from causal hypotheses.
Persist only explicit preferences or accepted decisions. Keep answers concise and cite IDs or sources."""


class ERPAState(TypedDict, total=False):
    messages: list[Any]
    message: str
    thread_id: str
    session_id: str
    user_id: str
    iterations: int
    started_at: float
    selected_tools: list[str]
    context: dict[str, Any]
    tool_results: list[dict[str, Any]]
    answer: str
    _trace_id: str
    _trace_spans: list[dict[str, Any]]
    _trace_recalled: list[dict[str, Any]]
    _trace_written: list[dict[str, Any]]
    _trace_tokens: int


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else [content]
    return "\n".join(
        str(block.get("text", "")) if isinstance(block, dict) else str(block)
        for block in blocks
        if not isinstance(block, dict) or block.get("type") == "text"
    ).strip()


def _span(state: ERPAState, name: str, kind: str, started: float, **attributes: Any) -> None:
    state.setdefault("_trace_spans", []).append({
        "name": name, "kind": kind, "status": "ok",
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "attributes": attributes,
    })


def compile_live_graph(checkpointer: Any) -> Any:
    """Compile the bounded Claude/tool loop with the supplied OracleSaver."""
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langgraph.graph import END, START, StateGraph

    from backend.core.memory import memory_provider
    from backend.core.scratchfs import ScratchFS, begin_session
    from backend.core.semantic import semantic_layer
    from backend.core.skills import disclose
    from backend.core.tools import custom_toolbox

    llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=8192,
        thinking={"type": settings.anthropic_thinking},
    )

    @traceable(name="graph.assemble_context", run_type="chain")
    def assemble_context(state: ERPAState) -> ERPAState:
        started = time.perf_counter()
        begin_session(state["session_id"], state["thread_id"], state["user_id"])
        filesystem = ScratchFS(state["session_id"])
        if not filesystem.exists("/plans/current.md"):
            filesystem.write("/plans/current.md", f"# Current objective\n{state['message']}\n")
        if not state.get("context"):
            recalled = memory_provider.recall(
                state["message"], state["user_id"], thread_id=state["thread_id"],
            )
            state["_trace_recalled"] = [{
                "type": item["memory_type"], "content": item["content"],
                "source": item["metadata"].get("source", "memory"),
            } for item in recalled]
        context = {
            "skill_manifest": disclose(state["message"]),
            "semantic_catalog": semantic_layer.search_catalog(state["message"], 5),
            "oamp_context_card": memory_provider.context_card(state["thread_id"], state["user_id"]),
            "scratch_plan": filesystem.read("/plans/current.md"),
        }
        exclusions = memory_provider.exclusions(state["user_id"])
        context["remembered_exclusions"] = exclusions
        state["selected_tools"] = custom_toolbox.discover_names(state["message"], 7)
        context["selected_tools"] = state["selected_tools"]
        state["context"] = context
        messages = [item for item in state["messages"] if not isinstance(item, SystemMessage)]
        state["messages"] = [SystemMessage(content=SYSTEM + "\n\n# SELECTIVE CONTEXT\n" + json.dumps(context, default=str))] + messages
        _span(state, "assemble_context", "graph_node", started,
              memory="OAMP", scratch="SecureFile", selected_tools=state["selected_tools"])
        return state

    @traceable(name="graph.call_model", run_type="llm")
    def call_model(state: ERPAState) -> ERPAState:
        started = time.perf_counter()
        selected = custom_toolbox.tools_for_names(state["selected_tools"])
        response = llm.bind_tools(selected).invoke(state["messages"])
        state["messages"].append(response)
        state["iterations"] = state.get("iterations", 0) + 1
        usage = getattr(response, "usage_metadata", None) or {}
        state["_trace_tokens"] = state.get("_trace_tokens", 0) + int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        _span(state, "call_model", "model", started,
              model=settings.anthropic_model, thinking=settings.anthropic_thinking,
              tool_schemas=len(selected), iteration=state["iterations"])
        return state

    @traceable(name="graph.dispatch_tools", run_type="chain")
    def dispatch_tools(state: ERPAState) -> ERPAState:
        started = time.perf_counter()
        ai = state["messages"][-1]
        called = []
        for call in getattr(ai, "tool_calls", []) or []:
            name, arguments = call["name"], dict(call.get("args", {}))
            if name in {"scratch_write", "scratch_read", "sandbox_python"}:
                arguments["session_id"] = state["session_id"]
            if name == "morning_brief_inputs":
                arguments["exclusions"] = state.get("context", {}).get("remembered_exclusions", [])
            result = custom_toolbox.invoke(name, arguments)
            called.append({"name": name, "arguments": arguments, "result": result})
            state.setdefault("tool_results", []).append({"name": name, "result": result})
            state["messages"].append(ToolMessage(
                content=json.dumps(result, default=str), tool_call_id=call["id"],
            ))
        _span(state, "dispatch_tools", "tool", started, tools=[item["name"] for item in called])
        return state

    @traceable(name="graph.finalize", run_type="chain")
    def finalize(state: ERPAState) -> ERPAState:
        started = time.perf_counter()
        messages = [item for item in state["messages"]
                    if not (isinstance(item, AIMessage) and getattr(item, "tool_calls", None) and not _message_text(item))]
        messages.append(HumanMessage(content=(
            "The tool budget is exhausted. Answer now using only the evidence already gathered. "
            "State any unresolved limitation explicitly."
        )))
        response = llm.invoke(messages)
        state["messages"].append(response)
        usage = getattr(response, "usage_metadata", None) or {}
        state["_trace_tokens"] = state.get("_trace_tokens", 0) + int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        _span(state, "finalize", "model", started, reason="iteration_or_wall_clock_budget")
        return state

    @traceable(name="graph.persist", run_type="chain")
    def persist(state: ERPAState) -> ERPAState:
        started = time.perf_counter()
        final = next((item for item in reversed(state["messages"])
                      if isinstance(item, AIMessage) and _message_text(item)), None)
        state["answer"] = _message_text(final) if final else "No final answer was produced."
        written = []
        if re.search(r"(?:don't|do not|stop) (?:showing|show|being shown).*accessories", state["message"], re.I):
            item = memory_provider.write(
                "semantic", "Exclude Accessories from recurring briefs and reviews",
                state["user_id"], {"source": "user_turn", "kind": "preference"},
                thread_id=state["thread_id"],
            )
            written.append({"type": "semantic", "content": item["content"],
                            "deduplicated": item.get("deduplicated", False)})
        item = memory_provider.write(
            "working", f"{state['thread_id']}: {state['message']} → completed",
            state["user_id"], {"source": "turn", "thread_id": state["thread_id"]},
            thread_id=state["thread_id"], ttl_days=7,
        )
        written.append({"type": "working", "content": item["content"],
                        "deduplicated": item.get("deduplicated", False)})
        memory_provider.persist_assistant_message(state["thread_id"], state["answer"], state["user_id"])
        state["_trace_written"] = written
        _span(state, "persist", "memory_write", started,
              provider="OAMP", checkpoint="OracleSaver")
        return state

    def route_after_model(state: ERPAState) -> str:
        ai = state["messages"][-1]
        wants_tools = bool(getattr(ai, "tool_calls", None))
        over_budget = (
            state.get("iterations", 0) >= settings.graph_max_iterations
            or time.monotonic() - state["started_at"] > settings.graph_timeout_seconds
        )
        if over_budget and wants_tools:
            return "finalize"
        return "persist" if not wants_tools else "tools"

    builder = StateGraph(ERPAState)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("call_model", call_model)
    builder.add_node("dispatch_tools", dispatch_tools)
    builder.add_node("finalize", finalize)
    builder.add_node("persist", persist)
    builder.add_edge(START, "assemble_context")
    builder.add_edge("assemble_context", "call_model")
    builder.add_conditional_edges(
        "call_model", route_after_model,
        {"tools": "dispatch_tools", "persist": "persist", "finalize": "finalize"},
    )
    builder.add_edge("dispatch_tools", "assemble_context")
    builder.add_edge("finalize", "persist")
    builder.add_edge("persist", END)
    return builder.compile(checkpointer=checkpointer)


class LiveOracleGraph:
    """App façade with OracleSemanticCache before the checkpointed graph."""

    graph = {
        "boundary": "OracleSemanticCache → (hit: return | miss: LangGraph)",
        "nodes": ["assemble_context", "call_model", "dispatch_tools", "finalize", "persist"],
        "edges": [
            "START→assemble_context", "assemble_context→call_model",
            "call_model→dispatch_tools|finalize|persist", "dispatch_tools→assemble_context",
            "finalize→persist", "persist→END",
        ],
        "runtime": "langgraph.StateGraph",
        "model": "ChatAnthropic claude-opus-4-8 (adaptive thinking)",
        "checkpointer": "langgraph_oracledb.OracleSaver (dedicated connection)",
        "semantic_cache": "langchain_oracledb.OracleSemanticCache + Oracle in-DB embeddings",
        "prompt_cache": "not implemented by design; stable-prefix seam documented",
    }

    def __init__(self, oracle_stack: Any) -> None:
        self.stack = oracle_stack
        self.compiled = compile_live_graph(oracle_stack.checkpointer)
        self.latest_trace: dict[str, Any] | None = None

    @traceable(name="erpa.appbook.run", run_type="chain")
    def run(
        self,
        message: str,
        thread_id: str = "demo-thread",
        user_id: str = settings.user_id,
        *,
        bypass_cache: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        trace_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        session_id = session_id or "session-" + hashlib.sha256(thread_id.encode()).hexdigest()[:24]
        hit = None if bypass_cache else semantic_cache.get(message, user_id)
        if hit:
            summary = {
                "trace_id": trace_id, "build": "custom-live", "shape": "recall → decide → write",
                "question": message, "recalled": [],
                "decision": {"intent": "cache_hit", "reason": f"semantic similarity {hit['similarity']}"},
                "written": [], "cache_hit": True, "tokens": 0,
                "tokens_avoided": hit.get("original_tokens", 0),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "spans": [{"name": "boundary_cache.lookup", "kind": "cache", "status": "hit",
                           "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                           "attributes": {"implementation": "OracleSemanticCache",
                                          "namespace": semantic_cache.namespace_for(user_id)}}],
            }
            self.latest_trace = summary
            return {
                "answer": hit["answer"], "data": hit.get("payload", {}).get("data"),
                "context": None, "trace": summary,
                "instrumentation": {"recall": [], "decide": summary["decision"], "write": []},
                "persistence": {"semantic_cache": "OracleSemanticCache", "model_span": False},
                "session_id": session_id,
            }

        config = {
            "configurable": {"thread_id": thread_id}, "recursion_limit": 50,
            "tags": ["erpa", "custom-harness", "appbook"],
            "metadata": {"session_id": session_id, "user_id": user_id,
                         "model": settings.anthropic_model, "thinking": settings.anthropic_thinking},
        }
        result = self.compiled.invoke({
            "messages": [HumanMessage(content=message)], "message": message,
            "thread_id": thread_id, "session_id": session_id, "user_id": user_id,
            "iterations": 0, "started_at": time.monotonic(), "tool_results": [],
            "_trace_id": trace_id, "_trace_spans": [], "_trace_recalled": [],
            "_trace_written": [], "_trace_tokens": 0,
        }, config=config)
        run_tree = get_current_run_tree()
        summary = {
            "trace_id": trace_id, "langsmith_run_id": str(run_tree.id) if run_tree else None,
            "build": "custom-live", "shape": "recall → decide → write", "question": message,
            "recalled": result.get("_trace_recalled", []),
            "decision": {"intent": "tool_loop", "selected_tools": result.get("selected_tools", []),
                         "iterations": result.get("iterations", 0)},
            "written": result.get("_trace_written", []), "cache_hit": False,
            "tokens": result.get("_trace_tokens", 0),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "spans": [{"name": "boundary_cache.lookup", "kind": "cache", "status": "miss",
                       "duration_ms": 0.0, "attributes": {"implementation": "OracleSemanticCache",
                                                           "namespace": semantic_cache.namespace_for(user_id)}},
                      *result.get("_trace_spans", [])],
        }
        data = {"tool_results": result.get("tool_results", [])}
        semantic_cache.put(message, result["answer"], {"data": data}, summary["tokens"], user_id)
        checkpointed = self.stack.checkpointer.get(config) is not None
        self.latest_trace = summary
        return {
            "answer": result["answer"], "data": data, "context": result.get("context"),
            "trace": summary,
            "instrumentation": {"recall": summary["recalled"], "decide": summary["decision"],
                                "write": summary["written"]},
            "persistence": {"semantic_cache": "OracleSemanticCache", "checkpointer": "OracleSaver",
                            "checkpointed": checkpointed, "thread_id": thread_id,
                            "scratchfs": "Oracle SecureFile", "session_id": session_id},
            "session_id": session_id,
        }


def invoke_with_cache(
    graph: Any, message: str, *, thread_id: str = "demo-thread",
    user_id: str = settings.user_id, bypass_cache: bool = False,
) -> dict[str, Any]:
    if not isinstance(graph, LiveOracleGraph):
        raise TypeError("Pass a LiveOracleGraph so OracleSaver persistence can be verified")
    return graph.run(message, thread_id, user_id, bypass_cache=bypass_cache)
