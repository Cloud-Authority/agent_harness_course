"""Explicit capability ledger for the custom harness appbook."""
from __future__ import annotations

from typing import Any


COMPONENTS: list[dict[str, str]] = [
    {"concern": "Agent loop", "component": "LangGraph StateGraph", "role": "Context → Claude → tools → persistence under explicit budgets", "status": "built"},
    {"concern": "Construction", "component": "Typed state + explicit factories", "role": "Wires model, memory, toolbox, skills, cache, tracing and checkpoints", "status": "built-custom"},
    {"concern": "Model adapter", "component": "ChatAnthropic / Claude Opus 4.8", "role": "Adaptive-thinking reasoning and tool selection", "status": "built"},
    {"concern": "Persona", "component": "SYSTEM instruction", "role": "Stable ERPA role, authority and safety policy", "status": "partial-no-lifecycle"},
    {"concern": "Application modes", "component": "—", "role": "Preconfigured assistant/workflow/research bundles", "status": "missing"},
    {"concern": "Database substrate", "component": "python-oracledb + Oracle AI Database Free", "role": "Business data, vectors, jobs, scratch, cache and checkpoints", "status": "built"},
    {"concern": "Conversation memory", "component": "OAMP thread messages", "role": "User/assistant episodic record by thread", "status": "built"},
    {"concern": "Knowledge memory", "component": "OAMP facts/guidelines + institutional corpus", "role": "Durable rules and approved institutional evidence", "status": "built"},
    {"concern": "Entity memory", "component": "OAMP facts + relational product/region tables", "role": "Facts about users, products, regions and purchase orders", "status": "partial-no-entity-api"},
    {"concern": "Working memory", "component": "OAMP context card + SecureFile ScratchFS", "role": "Bounded recent context, current plan, notes and artifacts", "status": "built"},
    {"concern": "Summaries", "component": "OAMP context summaries/cards", "role": "Prompt-ready conversation compression", "status": "partial-no-source-link-audit"},
    {"concern": "Semantic cache", "component": "langchain-oracledb OracleSemanticCache", "role": "Meaning-equivalent read-only answers before the graph", "status": "built"},
    {"concern": "Function tools", "component": "CustomToolbox + StructuredTool", "role": "Semantic discovery, schema disclosure, validation and allowlisted execution", "status": "built"},
    {"concern": "Tool-result compaction", "component": "E2B result → ScratchFS pointer", "role": "Keeps large generated-code output out of model context", "status": "partial-e2b-only"},
    {"concern": "Skills", "component": "Oracle ERPA_SKILL_REGISTRY", "role": "Retrieve a manifest and load one approved procedure", "status": "built-active-only"},
    {"concern": "Continual learning", "component": "Scratch → trigger → queue → OAMP", "role": "Promote selected session notes into durable memory", "status": "partial-no-skill-harvester"},
    {"concern": "MCP", "component": "—", "role": "External standardized tool/resource transports", "status": "missing"},
    {"concern": "Code sandbox", "component": "E2B Code Interpreter", "role": "Generated Python execution with no host fallback", "status": "built"},
    {"concern": "Multi-agent orchestration", "component": "—", "role": "Delegate bounded specialist work and consolidate it", "status": "missing-single-agent"},
    {"concern": "Automations", "component": "DBMS_SCHEDULER + queue worker", "role": "Weekday brief through the same graph", "status": "built"},
    {"concern": "Internet access", "component": "Governed external-signal ingestion", "role": "Dated outside evidence", "status": "partial-no-live-search"},
    {"concern": "Self-awareness", "component": "—", "role": "Guarded source inspection or mutation", "status": "missing"},
    {"concern": "Context telemetry", "component": "LangSmith + cache/model/tool counters", "role": "Execution spans and cache-bypass evidence", "status": "partial-no-token-window-dashboard"},
    {"concern": "Human in the loop", "component": "Host-owned approval ledger", "role": "Bind approval to a concrete side effect", "status": "partial-no-interrupt-resume"},
    {"concern": "Semantic layer", "component": "Views + comments + hints + V$SQL + vectors", "role": "Governed metrics, joins and living workload meaning", "status": "built"},
    {"concern": "Graph checkpoints", "component": "OracleSaver", "role": "Persist every graph super-step under thread_id", "status": "built"},
    {"concern": "Prompt caching", "component": "Stable-prefix design note", "role": "Future Anthropic input-token optimization", "status": "not-implemented-by-design"},
]


def component_map() -> dict[str, Any]:
    counts = {
        "built": sum(item["status"].startswith("built") for item in COMPONENTS),
        "partial": sum(item["status"].startswith("partial") for item in COMPONENTS),
        "missing": sum(item["status"].startswith("missing") for item in COMPONENTS),
        "not_implemented_by_design": sum(item["status"].startswith("not-implemented") for item in COMPONENTS),
    }
    return {"components": COMPONENTS, "counts": counts}
