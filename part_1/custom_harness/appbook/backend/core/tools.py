"""Trusted, meaning-retrieved function tools and the custom toolbox."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from backend.config import settings
from backend.core.sandbox import e2b_stock_chart, run_python_in_e2b, stock_chart
from backend.core.semantic import semantic_layer
from backend.core.skills import SKILLS

try:
    from langsmith import traceable
except ImportError:
    def traceable(*_args, **_kwargs):
        return lambda function: function


class CustomToolbox:
    """Join Oracle metadata discovery to a closed set of trusted callables."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {
            "morning_brief_inputs": {
                "description": "Return UK/EU low-stock actions and handled suppressions covered by open purchase orders",
                "keywords": "morning brief restock low stock purchase order suppress handled",
                "transport": "trusted Oracle function",
                "fn": self.morning_brief_inputs,
            },
            "sales_signal": {
                "description": "Compare recent product demand with the prior baseline and internal promotion state",
                "keywords": "sales demand WarmLayer spike change promotion baseline",
                "transport": "trusted Oracle function",
                "fn": self.sales_signal,
            },
            "inventory_status": {
                "description": "Read inventory by product, region, city and size",
                "keywords": "inventory stock region size curve ThermaCore",
                "transport": "trusted Oracle function",
                "fn": self.inventory_status,
            },
            "regional_profitability": {
                "description": "Rank regions with the governed gross-margin definition of profitability",
                "keywords": "profit profitable margin revenue region",
                "transport": "governed Oracle view",
                "fn": self.regional_profitability,
            },
            "institutional_search": {
                "description": "Retrieve approved internal playbooks, policy and regional merchandising evidence",
                "keywords": "institutional docs policy playbook seasonal guidance explanation",
                "transport": "Oracle vector retrieval",
                "fn": self.institutional_search,
            },
            "external_signal_search": {
                "description": "Read dated external signals from the governed ingestion layer",
                "keywords": "external outside weather cold snap source evidence",
                "transport": "governed Oracle ingestion table",
                "fn": self.external_signal_search,
            },
            "scratch_write": {
                "description": "Write or update a session plan, note, draft or tool artifact",
                "keywords": "plan notes scratch draft artifact filesystem",
                "transport": "Oracle SecureFile ScratchFS",
                "fn": self.scratch_write,
            },
            "scratch_read": {
                "description": "Read a file from the current session scratch mount",
                "keywords": "read plan notes scratch artifact filesystem",
                "transport": "Oracle SecureFile ScratchFS",
                "fn": self.scratch_read,
            },
            "sandbox_python": {
                "description": "Execute generated Python in E2B and compact large output to Oracle ScratchFS",
                "keywords": "python code compute chart render analyse sandbox",
                "transport": "E2B Code Interpreter",
                "fn": self.sandbox_python,
            },
            "remember_fact": {
                "description": "Persist an explicit preference, fact or reusable guideline",
                "keywords": "remember persist preference fact guideline memory",
                "transport": "Oracle Agent Memory",
                "fn": self.remember_fact,
            },
            "load_skill": {
                "description": "Load the full body of one retrieved approved procedure",
                "keywords": "skill procedure instructions workflow",
                "transport": "Oracle skill registry",
                "fn": self.load_skill,
            },
        }

    def catalog(self, include_callable: bool = False) -> list[dict[str, Any]]:
        result = []
        for name, spec in self._tools.items():
            item = {"name": name, **spec}
            result.append({
                key: value for key, value in item.items()
                if key != "keywords" and (include_callable or key != "fn")
            })
        return result

    @traceable(name="toolbox.discover", run_type="retriever")
    def discover(self, query: str, limit: int = 7) -> dict[str, Any]:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT tool_name,description,transport,
                          VECTOR_DISTANCE(embedding,VECTOR_EMBEDDING({settings.oamp_indb_embed_model}
                            USING :query AS DATA),COSINE) distance
                          FROM erpa_tool_registry ORDER BY distance
                          FETCH APPROX FIRST :limit ROWS ONLY""",
                        {"query": query, "limit": limit},
                    )
                    columns = [item[0].lower() for item in cursor.description]
                    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                connection.close()
            return {"query": query, "tools": [row for row in rows if row["tool_name"] in self._tools]}

        stop = {"the", "and", "did", "why", "last", "week", "show", "what", "which", "this"}
        words = {word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2 and word not in stop}
        ranked = []
        for name, spec in self._tools.items():
            corpus = f"{name} {spec['description']} {spec['keywords']}".lower()
            score = len(words & set(re.findall(r"[a-z0-9]+", corpus)))
            if score or name == "morning_brief_inputs":
                ranked.append((score, {
                    "name": name, "description": spec["description"],
                    "transport": spec["transport"], "distance": None,
                }))
        rows = [item for _, item in sorted(ranked, key=lambda pair: (-pair[0], pair[1]["name"]))[:limit]]
        return {"query": query, "tools": rows}

    def retrieve(self, query: str, limit: int = 7) -> list[dict[str, Any]]:
        return self.discover(query, limit)["tools"]

    def discover_names(self, query: str, limit: int = 7) -> list[str]:
        return [item["name"] for item in self.discover(query, limit)["tools"]]

    def tools_for_names(self, names: list[str]) -> list[Any]:
        """Expose only retrieved schemas as LangChain StructuredTools."""
        from langchain_core.tools import StructuredTool

        tools = []
        for name in names:
            if name not in self._tools:
                continue
            spec = self._tools[name]
            tools.append(StructuredTool.from_function(
                func=spec["fn"], name=name, description=spec["description"],
            ))
        return tools

    @traceable(name="toolbox.invoke", run_type="tool")
    def invoke(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        function = self._tools.get(tool_name)
        if function is None:
            return {"error": "tool_not_allowed", "tool_name": tool_name}
        try:
            return function["fn"](**(arguments or {}))
        except Exception as exc:
            return {
                "error": "invalid_or_failed_tool_call", "tool_name": tool_name,
                "error_type": type(exc).__name__, "detail": str(exc),
            }

    def call(self, name: str, **kwargs: Any) -> Any:
        """Compatibility entry point used by the deterministic local graph."""
        if name == "semantic_query":
            return semantic_layer.ask(kwargs["question"], kwargs.get("exclusions"))["result"]
        result = self.invoke(name, kwargs)
        if isinstance(result, dict) and result.get("error"):
            raise ValueError(result["detail"])
        return result

    def morning_brief_inputs(
        self, excluded_category: str = "", exclusions: list[str] | None = None,
    ) -> dict[str, Any]:
        excluded = list(exclusions or [])
        if excluded_category:
            excluded.append(excluded_category)
        result = semantic_layer.data.morning_brief(excluded or None)
        return {"new_actions": result["restock"], "suppressed": result["suppressed"], "as_of": result["as_of"]}

    def sales_signal(self, product_line: str, region: str) -> dict[str, Any]:
        if product_line.casefold() != "warmlayer" or region.casefold() != "uk":
            return {"error": "no governed fixture for that product/region"}
        internal = semantic_layer.data.warmlayer_spike()["internal"]
        return {
            "product_line": product_line, "region": region,
            "current_units": internal["last_7d_units"],
            "prior_weekly_average": internal["prior_weekly_average"],
            "change_percent": internal["change_percent"], "internal_promotion": False,
            "provenance": internal["provenance"],
        }

    def inventory_status(self, product_line: str = "ThermaCore") -> list[dict[str, Any]]:
        if product_line.casefold() != "thermacore":
            return []
        return semantic_layer.data.thermacore_stock()["rows"]

    def regional_profitability(self) -> dict[str, Any]:
        return semantic_layer.data.profitability()

    def institutional_search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            hits = get_oracle_stack().vector_store.similarity_search_with_score(query, k=limit)
            return [{
                "title": document.metadata.get("title"),
                "source": document.metadata.get("page"),
                "excerpt": document.page_content[:600], "distance": float(score),
            } for document, score in hits]
        return semantic_layer.data.search_docs(query, limit=limit)

    def external_signal_search(self, region: str, signal_type: str = "weather") -> list[dict[str, Any]]:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT observed_at,region,signal_type,summary,source_url FROM erpa_external_signals "
                        "WHERE UPPER(region)=UPPER(:1) AND UPPER(signal_type)=UPPER(:2) ORDER BY observed_at DESC",
                        [region, signal_type],
                    )
                    columns = [item[0].lower() for item in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                connection.close()
        external = semantic_layer.data.warmlayer_spike()["external"]
        return [{
            "observed_at": "fixture", "region": region, "signal_type": signal_type,
            "summary": external["signal"], "source_url": external["url"],
        }]

    def scratch_write(
        self, session_id: str, path: str, content: str, promote_on_end: bool = False,
    ) -> dict[str, Any]:
        from backend.core.scratchfs import ScratchFS
        return ScratchFS(session_id).write(path, content, promote_on_end=promote_on_end)

    def scratch_read(self, session_id: str, path: str) -> str:
        from backend.core.scratchfs import ScratchFS
        return ScratchFS(session_id).read(path)

    def sandbox_python(
        self, session_id: str, code: str, artifact_path: str = "/tool_out/result.json",
    ) -> dict[str, Any]:
        return run_python_in_e2b(session_id, code, artifact_path)

    def remember_fact(self, content: str, memory_type: str = "preference") -> dict[str, Any]:
        from backend.core.memory import memory_provider

        mapping = {"preference": "semantic", "fact": "semantic", "guideline": "procedural"}
        if memory_type not in mapping:
            raise ValueError("memory_type must be preference, fact, or guideline")
        item = memory_provider.write(
            mapping[memory_type], content, settings.user_id,
            {"source": "explicit_tool", "kind": memory_type},
        )
        return {"memory_id": item["memory_id"], "memory_type": memory_type}

    def load_skill(self, skill_name: str) -> dict[str, Any]:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT body,body_sha256 FROM erpa_skill_registry "
                        "WHERE skill_name=:1 AND status='ACTIVE'",
                        [skill_name],
                    )
                    row = cursor.fetchone()
            finally:
                connection.close()
            if not row:
                return {"error": "skill_not_found"}
            body = row[0].read() if hasattr(row[0], "read") else row[0]
            return {"body": body, "body_sha256": row[1]}
        item = SKILLS.get(skill_name)
        return {"body": item["instructions"]} if item else {"error": "skill_not_found"}

    def stock_visual(self, session_id: str) -> dict[str, Any]:
        data = semantic_layer.data.thermacore_stock()
        if settings.live:
            return {**data, **e2b_stock_chart(session_id, data["rows"])}
        return {
            **data, "chart_svg": stock_chart(data["rows"]),
            "file_pointer": "dbfs://local-inline",
            "sandbox": "deterministic local teaching mirror; generated code is disabled",
        }


custom_toolbox = CustomToolbox()
tool_registry = custom_toolbox
ToolRegistry = CustomToolbox
