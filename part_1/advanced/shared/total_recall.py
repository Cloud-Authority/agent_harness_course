"""Total Recall harness: memory, semantic registries, ontology GraphRAG, and context."""

from __future__ import annotations

import json
import operator
import threading
import uuid
from typing import Annotated, Any, Mapping, TypedDict

from langgraph.graph import END, START, StateGraph

from .agent_memory import create_agent_memory_manager
from .catalog import HarnessCatalog
from .config import ADVANCED_DIR, AdvancedSettings, settings as default_settings
from .fixtures import PROCEDURAL_MEMORY, SEMANTIC_MEMORY
from .inspector import context_window
from .ontology import OntologyStore
from .persistence import SemanticEncoder, create_persistence, json_safe, utcnow
from .workflow_tools import SandboxedToolExecutor, _sandbox_program


SKILL_ROOT = ADVANCED_DIR / "total_recall" / "skills"


class TotalRecallState(TypedDict, total=False):
    thread_id: str
    question: str
    memory_context: dict[str, Any]
    skill_candidates: list[dict[str, Any]]
    skill_manifest: str
    loaded_skills: list[dict[str, Any]]
    tool_candidates: list[dict[str, Any]]
    selected_tools: list[str]
    graph_retrieval: dict[str, Any]
    answer_result: dict[str, Any]
    verification: dict[str, Any]
    workflow_recipe: dict[str, Any]
    promotion: dict[str, Any]
    context_window: dict[str, Any]
    sandbox_trace: Annotated[list[dict[str, Any]], operator.add]
    audit: Annotated[list[dict[str, Any]], operator.add]


def count_affected_entities(node_ids: list[str]) -> dict[str, Any]:
    """Compute one untrusted post-processing metric in a disposable sandbox."""

    unique = sorted({str(item) for item in node_ids})
    return {
        "unique_entity_count": len(unique),
        "duplicates_removed": len(node_ids) - len(unique),
        "node_ids": unique,
    }


class TotalRecallHarness:
    """One inspectable agent loop over the new ontology layer."""

    def __init__(
        self,
        *,
        course_settings: AdvancedSettings = default_settings,
        auto_compile: bool = True,
    ) -> None:
        self.settings = course_settings
        self.resources = create_persistence(course_settings, enable_vector_search=False)
        self.encoder = SemanticEncoder(course_settings, pool=self.resources.pool)
        self.catalog = HarnessCatalog(
            course_settings, pool=self.resources.pool, encoder=self.encoder
        )
        self.ontology = OntologyStore(
            course_settings, pool=self.resources.pool, encoder=self.encoder
        )
        self.agent_memory = create_agent_memory_manager(
            course_settings, pool=self.resources.pool
        )
        self.agent_memory.seed_governance(
            procedural=PROCEDURAL_MEMORY, semantic=SEMANTIC_MEMORY
        )
        self._register_tools()
        self.seeded_skills = self.catalog.seed_skill_files(SKILL_ROOT)
        self.tool_executor = SandboxedToolExecutor(self.catalog, course_settings)
        self._compiled: Any = None
        self._latest_thread_id: str | None = None
        self._lock = threading.RLock()
        if auto_compile:
            self.compile_graph()

    @staticmethod
    def _sandbox_boundary_program() -> str:
        return (
            "raise RuntimeError('Ontology database capabilities execute through the "
            "least-privilege host data provider, not an arbitrary code sandbox.')\n"
        )

    def _register_tools(self) -> None:
        object_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 3},
                "k": {"type": "integer", "minimum": 1, "maximum": 12},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        self.catalog.register_tool(
            "ontology_search",
            lambda query, k=4: self.ontology.semantic_seeds(query, k=k),
            "Find governed ontology instances by semantic meaning and return stable IDs and distances.",
            object_schema,
            sandbox_program=self._sandbox_boundary_program(),
            synonyms=("knowledge graph seed search", "entity retrieval", "semantic entity lookup"),
            examples=("find the expired Northstar certificate", "find entities related to delayed winter orders"),
            when_to_use="before graph traversal when the operator starts with natural language",
            when_not="to claim that two entities are related",
            category="ontology-retrieval",
        )
        self.catalog.register_tool(
            "trace_business_impact",
            lambda query, max_hops=4: self.ontology.retrieve(
                query, k=4, max_hops=max_hops
            ),
            "Traverse validated stored ontology relationships from semantically retrieved seeds.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 3},
                    "max_hops": {"type": "integer", "minimum": 1, "maximum": 6},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            sandbox_program=self._sandbox_boundary_program(),
            synonyms=("blast radius", "dependency path", "multi-hop graph traversal"),
            examples=("trace certificate expiry to orders and contracts",),
            when_to_use="after entity seed retrieval when a relationship-grounded answer is required",
            when_not="when no stored edge exists",
            category="knowledge-graph",
        )
        self.catalog.register_tool(
            "inspect_ontology_term",
            lambda term_id: next(
                (item for item in self.ontology.terms() if item["term_id"] == term_id),
                {"error": "no such ontology term"},
            ),
            "Load one governed class or property definition, including domain and range.",
            {
                "type": "object",
                "properties": {"term_id": {"type": "string", "minLength": 1}},
                "required": ["term_id"],
                "additionalProperties": False,
            },
            sandbox_program=self._sandbox_boundary_program(),
            synonyms=("ontology schema", "class definition", "property contract"),
            examples=("inspect supplies", "inspect Evidence"),
            when_to_use="when a retrieved term's governed meaning is unclear",
            when_not="to modify ontology definitions",
            category="ontology-governance",
        )
        self.catalog.register_tool(
            "refresh_ontology_projection",
            lambda trigger="manual": self.ontology.refresh(trigger=trigger),
            "Refresh operational objects and links into the validated ontology projection.",
            {
                "type": "object",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "enum": ["manual", "scheduler"],
                    }
                },
                "additionalProperties": False,
            },
            sandbox_program=self._sandbox_boundary_program(),
            synonyms=("refresh graph", "rebuild semantic projection", "run ontology scheduler"),
            examples=("refresh after source records change",),
            when_to_use="when source data changed or the scheduled projection is stale",
            when_not="to create a native RDF network or grant database privileges",
            category="ontology-operations",
        )
        self.catalog.register_tool(
            "count_affected_entities",
            count_affected_entities,
            "Count unique affected ontology entity IDs in a disposable, egress-blocked sandbox.",
            {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["node_ids"],
                "additionalProperties": False,
            },
            sandbox_program=_sandbox_program(count_affected_entities),
            synonyms=("impact count", "unique affected objects", "blast radius size"),
            examples=("count the entities returned by graph traversal",),
            when_to_use="after graph traversal for untrusted deterministic post-processing",
            when_not="to retrieve or modify database records",
            category="sandboxed-post-processing",
        )

    def _event(self, thread_id: str, event_type: str, **detail: Any) -> dict[str, Any]:
        return {
            "event_id": uuid.uuid4().hex,
            "thread_id": thread_id,
            "event_type": event_type,
            "timestamp": utcnow(),
            "detail": json_safe(detail),
        }

    def build_graph(self) -> StateGraph:
        graph = StateGraph(TotalRecallState)

        def recall_memory(state: TotalRecallState) -> dict[str, Any]:
            memory = self.agent_memory.recall_context(
                state["thread_id"], state["question"]
            )
            return {
                "memory_context": memory,
                "audit": [self._event(state["thread_id"], "memory_recalled")],
            }

        def retrieve_skills(state: TotalRecallState) -> dict[str, Any]:
            candidates = self.catalog.retrieve_skills(state["question"], k=10)
            names = {item["name"] for item in candidates}
            required = ["supply-chain-impact-analysis"]
            if re_mentions_refresh(state["question"]):
                required.append("ontology-refresh-governance")
            missing = [name for name in required if name not in names]
            if missing:
                raise RuntimeError(
                    "Semantic Skillbox did not retrieve required ontology Skills: "
                    + ", ".join(missing)
                )
            loaded = [self.catalog.load_skill(name) for name in required]
            manifest = "\n".join(
                f"- {item['name']}: {item['description']} [sha:{item['sha'][:12]}]"
                for item in candidates
            )
            return {
                "skill_candidates": candidates,
                "skill_manifest": manifest,
                "loaded_skills": loaded,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "skills_loaded",
                        names=required,
                        progressive_disclosure=True,
                    )
                ],
            }

        def retrieve_tools(state: TotalRecallState) -> dict[str, Any]:
            authorized = []
            for skill in state["loaded_skills"]:
                for name in skill["tools_used"]:
                    if name not in authorized:
                        authorized.append(name)
            candidates = self.catalog.retrieve_tools(
                state["question"] + " " + " ".join(authorized), k=20
            )
            retrieved = {item["name"] for item in candidates}
            missing = sorted(set(authorized) - retrieved)
            if missing:
                raise RuntimeError(
                    "Semantic Toolbox did not retrieve required ontology tools: "
                    + ", ".join(missing)
                )
            return {
                "tool_candidates": candidates,
                "selected_tools": authorized,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "tools_bound",
                        selected=authorized,
                    )
                ],
            }

        def retrieve_graph(state: TotalRecallState) -> dict[str, Any]:
            if "trace_business_impact" not in state["selected_tools"]:
                raise RuntimeError("Graph traversal tool was not Skill-authorized")
            value = self.catalog.resolve_tool("trace_business_impact")["fn"](
                state["question"], max_hops=4
            )
            sandbox = self.tool_executor.execute(
                "count_affected_entities",
                {"node_ids": [item["node_id"] for item in value["affected_nodes"]]},
            )
            return {
                "graph_retrieval": value,
                "sandbox_trace": [sandbox],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "graph_retrieved",
                        seeds=len(value["seed_nodes"]),
                        paths=len(value["paths"]),
                    )
                ],
            }

        def call_model(state: TotalRecallState) -> dict[str, Any]:
            contracts = [
                item["tool_schema"]
                for item in state["tool_candidates"]
                if item["name"] in set(state["selected_tools"])
            ]
            result = self.ontology.answer(
                state["question"],
                thread_id=state["thread_id"],
                skill_manifest=state["skill_manifest"],
                tool_contracts=contracts,
                memory_context=state["memory_context"],
            )
            return {
                "answer_result": result,
                "context_window": result["context_window"],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "answer_synthesized",
                        provider=result["model"]["provider"],
                        actual_model_call=result["model"]["actual_call"],
                    )
                ],
            }

        def verify(state: TotalRecallState) -> dict[str, Any]:
            result = state["answer_result"]
            known_nodes = {
                f"KG:NODE:{item['node_id']}"
                for item in result["retrieval"]["seed_nodes"]
            }
            known_paths = {
                f"KG:PATH:{item['path_id']}"
                for item in result["retrieval"]["paths"]
            }
            citations = set(result["citations"])
            checks = {
                "semantic_seeds_present": bool(known_nodes),
                "stored_paths_present": bool(known_paths),
                "citations_resolve": citations <= (known_nodes | known_paths),
                "edge_contracts_valid": bool(result["verified"]),
                "context_window_visible": bool(state["context_window"]["sections"]),
                "sandbox_output_recomputed": bool(
                    state.get("sandbox_trace")
                    and state["sandbox_trace"][-1]["output"]["host_recomputation_matched"]
                    and state["sandbox_trace"][-1]["execution"]["session_closed"]
                ),
            }
            verified = all(checks.values())
            if not verified:
                raise RuntimeError("Ontology-grounded answer failed host verification")
            event = self._event(
                state["thread_id"], "answer_verified", checks=checks
            )
            self.agent_memory.record_event(event)
            return {
                "verification": {"verified": verified, "checks": checks},
                "audit": [event],
            }

        def capture_workflow(state: TotalRecallState) -> dict[str, Any]:
            recipe = self.catalog.capture_workflow(
                intent=(
                    "Answer an enterprise impact question by recalling governed context, "
                    "retrieving a procedural Skill and minimal Tool contracts by meaning, "
                    "selecting graph seeds semantically, traversing stored ontology edges, "
                    "sandboxing post-processing, and verifying citations in the host."
                ),
                steps=[
                    {"step": 1, "action": "recall scoped memory"},
                    {"step": 2, "action": "retrieve and load relevant SKILL.md"},
                    {"step": 3, "action": "retrieve authorized tool contracts"},
                    {"step": 4, "action": "find semantic seeds and traverse stored edges"},
                    {"step": 5, "action": "run post-processing in a disposable sandbox"},
                    {"step": 6, "action": "synthesize from nodes and paths only"},
                    {"step": 7, "action": "verify citations, edge contracts, and sandbox output"},
                ],
                tools_used=state["selected_tools"],
                success=bool(state["verification"]["verified"]),
            )
            return {
                "workflow_recipe": recipe,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "workflow_captured",
                        recipe_id=recipe["recipe_id"],
                        occurrences=recipe["occurrences"],
                    )
                ],
            }

        def promote_skill(state: TotalRecallState) -> dict[str, Any]:
            recipe = state["workflow_recipe"]
            criteria = {
                "recurs": recipe["occurrences"]
                >= self.settings.skill_promotion_min_occurrences,
                "reliable": recipe["successes"] > recipe["failures"],
                "last_run_verified": recipe["last_outcome"] == "success",
            }
            if recipe.get("promoted"):
                result = {
                    "status": "already_promoted",
                    "skill_name": recipe.get("promoted_skill_name"),
                    "criteria": criteria,
                    "source_workflow_id": recipe["recipe_id"],
                }
            elif all(criteria.values()):
                name = "proven-ontology-impact-analysis"
                description = (
                    "Run a recurring verified ontology impact analysis with semantic "
                    "retrieval, stored paths, sandboxed metrics, and host citation checks."
                )
                tools = list(recipe["tools_used"])
                skill_md = (
                    "---\n"
                    f"name: {name}\n"
                    f"description: {description}\n"
                    f"tools: [{', '.join(tools)}]\n"
                    "---\n\n"
                    "# Proven ontology impact analysis\n\n"
                    "## Parameters\n\n- `question`: the enterprise impact question.\n"
                    "- `max_hops`: the bounded traversal depth.\n\n"
                    "## Steps\n\n"
                    "1. Recall scoped memory and retrieve the smallest relevant Skill manifest.\n"
                    "2. Load the full selected SKILL.md and bind only its Tool contracts.\n"
                    "3. Use vector similarity only to select seed entity IDs.\n"
                    "4. Establish impact only through stored, domain/range-valid ontology edges.\n"
                    "5. Run derived counts in a disposable sandbox with no forwarded secrets.\n"
                    "6. Preserve node IDs, path IDs, predicates, and evidence references.\n"
                    "7. Let the host verify citations, edge contracts, sandbox recomputation, and teardown.\n\n"
                    "## Guardrails\n\n"
                    "- Never turn vector proximity into a relationship claim.\n"
                    "- Never invent an edge, source status, approval, or successful refresh.\n"
                    "- Retire the raw workflow recipe from default recall after promotion.\n"
                )
                sha = self.catalog.save_skill(
                    name,
                    description,
                    skill_md,
                    tools,
                    source_workflow_id=recipe["recipe_id"],
                    source_url="generated:verified-ontology-workflow",
                )
                self.catalog.mark_promoted(recipe["recipe_id"], name)
                result = {
                    "status": "promoted",
                    "skill_name": name,
                    "sha": sha,
                    "criteria": criteria,
                    "source_workflow_id": recipe["recipe_id"],
                    "raw_recipe_retired_from_default_recall": True,
                }
            else:
                result = {
                    "status": "candidate",
                    "criteria": criteria,
                    "source_workflow_id": recipe["recipe_id"],
                    "progress": {
                        "occurrences": recipe["occurrences"],
                        "required": self.settings.skill_promotion_min_occurrences,
                        "successes": recipe["successes"],
                        "failures": recipe["failures"],
                    },
                }
            return {
                "promotion": result,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "skill_promotion_evaluated",
                        status=result["status"],
                    )
                ],
            }

        for name, node in (
            ("recall_memory", recall_memory),
            ("retrieve_skills", retrieve_skills),
            ("retrieve_tools", retrieve_tools),
            ("retrieve_graph", retrieve_graph),
            ("call_model", call_model),
            ("verify", verify),
            ("capture_workflow", capture_workflow),
            ("promote_skill", promote_skill),
        ):
            graph.add_node(name, node)
        graph.add_edge(START, "recall_memory")
        graph.add_edge("recall_memory", "retrieve_skills")
        graph.add_edge("retrieve_skills", "retrieve_tools")
        graph.add_edge("retrieve_tools", "retrieve_graph")
        graph.add_edge("retrieve_graph", "call_model")
        graph.add_edge("call_model", "verify")
        graph.add_edge("verify", "capture_workflow")
        graph.add_edge("capture_workflow", "promote_skill")
        graph.add_edge("promote_skill", END)
        return graph

    def compile_graph(self) -> Any:
        with self._lock:
            if self._compiled is None:
                self._compiled = self.build_graph().compile(
                    checkpointer=self.resources.checkpointer
                )
            return self._compiled

    @property
    def graph(self) -> Any:
        return self.compile_graph()

    def graph_mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()

    def run(
        self, question: str | None = None, *, thread_id: str | None = None
    ) -> dict[str, Any]:
        resolved_thread = thread_id or f"total-recall-{uuid.uuid4().hex[:10]}"
        resolved_question = str(question or self.ontology.default_question()).strip()
        self._latest_thread_id = resolved_thread
        config = {"configurable": {"thread_id": resolved_thread}}
        result = self.graph.invoke(
            {
                "thread_id": resolved_thread,
                "question": resolved_question,
                "audit": [],
                "sandbox_trace": [],
            },
            config=config,
        )
        return {
            "status": "succeeded",
            "thread_id": resolved_thread,
            "state": json_safe(result),
            "answer": result["answer_result"]["answer"],
            "citations": result["answer_result"]["citations"],
            "verification": result["verification"],
            "promotion": result["promotion"],
            "context_window": result["context_window"],
            "workflow_view": self.workflow_view(result),
        }

    def workflow_view(self, state: Mapping[str, Any] | None = None) -> dict[str, Any]:
        completed = bool(state and state.get("verification", {}).get("verified"))
        ids = [
            "start",
            "recall_memory",
            "retrieve_skills",
            "retrieve_tools",
            "retrieve_graph",
            "call_model",
            "verify",
            "capture_workflow",
            "promote_skill",
            "end",
        ]
        return {
            "nodes": [
                {
                    "id": name,
                    "label": name.replace("_", " ").title(),
                    "status": "completed" if completed else "pending",
                    "kind": "boundary" if name in {"start", "end"} else "harness_node",
                }
                for name in ids
            ],
            "edges": [
                {"source": left, "target": right}
                for left, right in zip(ids, ids[1:])
            ],
            "run_status": "succeeded" if completed else "awaiting_run",
        }

    def context_window(self) -> dict[str, Any]:
        if not self._latest_thread_id:
            return self.ontology.context_snapshot()
        snapshot = self.graph.get_state(
            {"configurable": {"thread_id": self._latest_thread_id}}
        )
        values = dict(snapshot.values or {})
        return json_safe(
            values.get("context_window") or self.ontology.context_snapshot()
        )

    def status(self) -> dict[str, Any]:
        return {
            "ready": True,
            "section": "total_recall",
            "architecture": "memory + semantic registries + ontology vector seeds + graph traversal + visible context",
            "persistence": {
                "backend": self.resources.backend,
                "checkpointer": type(self.resources.checkpointer).__name__,
                "oracle_version": self.resources.oracle_version,
            },
            "memory": self.agent_memory.status(),
            "catalog": self.catalog.status(),
            "ontology": self.ontology.status(),
            "workflow_view": self.workflow_view(),
            "default_question": self.ontology.default_question(),
            "skills": [item["name"] for item in self.seeded_skills],
            "tools": [
                "ontology_search",
                "trace_business_impact",
                "inspect_ontology_term",
                "refresh_ontology_projection",
                "count_affected_entities",
            ],
            "sandbox": self.tool_executor.status(),
            "promotion_policy": {
                "minimum_occurrences": self.settings.skill_promotion_min_occurrences,
                "reliability": "successes > failures",
                "verification": "last outcome must be host-verified success",
                "result": "SHA-versioned SKILL.md; raw recipe retired from default recall",
            },
        }

    def explorer_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        values = self.ontology.explorer_snapshot()
        if self.settings.backend == "memory":
            values["semantic_toolbox"] = [
                {key: value for key, value in row.items() if key != "embedding"}
                for row in self.catalog._tools.values()
            ]
            values["semantic_skillbox"] = [
                {key: value for key, value in row.items() if key != "embedding"}
                for row in self.catalog._skills.values()
            ]
        return values

    def close(self) -> None:
        self.agent_memory.close()
        self.resources.close()


def re_mentions_refresh(question: str) -> bool:
    text = str(question).lower()
    return any(token in text for token in ("refresh", "scheduler", "stale", "ontology job"))


__all__ = ["TotalRecallHarness", "TotalRecallState"]
