"""LLM-planned durable supplier workflow with semantic catalogs and sandboxed tools."""

from __future__ import annotations

import operator
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Mapping, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .agent_memory import create_agent_memory_manager
from .catalog import HarnessCatalog
from .config import AdvancedSettings, settings as default_settings
from .fixtures import PROCEDURAL_MEMORY, SEMANTIC_MEMORY
from .inspector import context_window
from .model_provider import create_report_drafter
from .persistence import (
    PersistenceResources,
    ScopedMemory,
    create_persistence,
    json_safe,
    stable_hash,
    utcnow,
)
from .promotion import WorkflowSkillPromoter
from .workflow_tools import SandboxedToolExecutor, register_workflow_tools


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "workflow" / "skills"


class WorkflowState(TypedDict, total=False):
    thread_id: str
    case_id: str
    objective: str
    requested_by: str
    fail_once_at: str
    context: dict[str, Any]
    skill_candidates: list[dict[str, Any]]
    skill_manifest: str
    plan: dict[str, Any]
    loaded_skills: list[dict[str, Any]]
    tool_candidates: list[dict[str, Any]]
    selected_tools: list[str]
    source_case: dict[str, Any]
    freshness_result: dict[str, Any]
    sanctions_result: dict[str, Any]
    risk_assessment: dict[str, Any]
    remediation_plan: dict[str, Any]
    findings: list[dict[str, Any]]
    draft: dict[str, Any]
    approval: dict[str, Any]
    publication: dict[str, Any]
    verification: dict[str, Any]
    workflow_recipe: dict[str, Any]
    promotion: dict[str, Any]
    outcome: str
    sandbox_trace: Annotated[list[dict[str, Any]], operator.add]
    audit: Annotated[list[dict[str, Any]], operator.add]
    idempotency: Annotated[list[dict[str, Any]], operator.add]


@dataclass
class OperationResult:
    value: dict[str, Any]
    reused: bool
    key: str


class WorkflowHarness:
    """Operational harness around an LLM-planned, long-running compliance graph."""

    application = "workflow"
    workflow_nodes = [
        {"id": "start", "label": "Start", "kind": "boundary", "x": 70, "y": 250},
        {"id": "load_context", "label": "Recall memory", "kind": "memory", "x": 230, "y": 250},
        {"id": "retrieve_skills", "label": "Find skills", "kind": "skillbox", "x": 410, "y": 250},
        {"id": "plan_review", "label": "LLM plan", "kind": "model", "x": 590, "y": 250},
        {"id": "retrieve_tools", "label": "Find tools", "kind": "toolbox", "x": 770, "y": 250},
        {"id": "collect_case", "label": "Load case", "kind": "sandbox_tool", "x": 950, "y": 250},
        {"id": "validate_evidence", "label": "Check evidence", "kind": "sandbox_tool", "x": 1130, "y": 250},
        {"id": "screen_sanctions", "label": "Screen sanctions", "kind": "sandbox_tool", "x": 1310, "y": 250},
        {"id": "assess_risk", "label": "Score risk", "kind": "sandbox_tool", "x": 1490, "y": 250},
        {"id": "build_remediation", "label": "Plan remediation", "kind": "sandbox_tool", "x": 1670, "y": 250},
        {"id": "draft_report", "label": "LLM draft", "kind": "model", "x": 1850, "y": 250},
        {"id": "approval_gate", "label": "Human decision", "kind": "interrupt", "x": 2030, "y": 250},
        {"id": "publish", "label": "Publish once", "kind": "side_effect", "x": 2210, "y": 135},
        {"id": "reject", "label": "Record rejection", "kind": "terminal", "x": 2210, "y": 365},
        {"id": "verify_result", "label": "Verify package", "kind": "sandbox_tool", "x": 2390, "y": 135},
        {"id": "capture_workflow", "label": "Capture recipe", "kind": "workflow_memory", "x": 2570, "y": 250},
        {"id": "promote_skill", "label": "Promote skill", "kind": "learning", "x": 2750, "y": 250},
        {"id": "end", "label": "End", "kind": "boundary", "x": 2920, "y": 250},
    ]
    workflow_edges = [
        {"source": "start", "target": "load_context"},
        {"source": "load_context", "target": "retrieve_skills"},
        {"source": "retrieve_skills", "target": "plan_review"},
        {"source": "plan_review", "target": "retrieve_tools"},
        {"source": "retrieve_tools", "target": "collect_case"},
        {"source": "collect_case", "target": "validate_evidence"},
        {"source": "validate_evidence", "target": "screen_sanctions"},
        {"source": "screen_sanctions", "target": "assess_risk"},
        {"source": "assess_risk", "target": "build_remediation"},
        {"source": "build_remediation", "target": "draft_report"},
        {"source": "draft_report", "target": "approval_gate"},
        {"source": "approval_gate", "target": "publish", "label": "approve"},
        {"source": "approval_gate", "target": "reject", "label": "reject"},
        {"source": "publish", "target": "verify_result"},
        {"source": "verify_result", "target": "capture_workflow"},
        {"source": "reject", "target": "capture_workflow"},
        {"source": "capture_workflow", "target": "promote_skill"},
        {"source": "promote_skill", "target": "end"},
    ]

    def __init__(
        self,
        *,
        course_settings: AdvancedSettings = default_settings,
        resources: PersistenceResources | None = None,
        drafter: Any = None,
        catalog: HarnessCatalog | None = None,
        tool_executor: SandboxedToolExecutor | None = None,
        auto_compile: bool = True,
    ) -> None:
        self.settings = course_settings
        self.resources = resources or create_persistence(
            course_settings, enable_vector_search=False
        )
        self._owns_resources = resources is None
        self.ledger = ScopedMemory(
            self.resources.store, tenant_id=course_settings.tenant_id
        )
        self.agent_memory = create_agent_memory_manager(
            course_settings, pool=self.resources.pool
        )
        self.model_provider = drafter or create_report_drafter(course_settings)
        self.drafter = self.model_provider
        self.catalog = catalog or HarnessCatalog(
            course_settings, pool=self.resources.pool
        )
        self.registered_tools = register_workflow_tools(self.catalog)
        self.seeded_skills = self.catalog.seed_skill_files(SKILLS_ROOT)
        self.tool_executor = tool_executor or SandboxedToolExecutor(
            self.catalog, course_settings
        )
        self.promoter = WorkflowSkillPromoter(
            self.catalog,
            self.model_provider,
            min_occurrences=course_settings.skill_promotion_min_occurrences,
        )
        self._lock = threading.RLock()
        self._last_errors: dict[str, dict[str, Any]] = {}
        self._latest_thread_id: str | None = None
        self._seed_governance_memory()
        self.graph_builder = self.build_graph()
        self.graph: Any = None
        if auto_compile:
            self.compile_graph()

    def _seed_governance_memory(self) -> None:
        self.agent_memory.seed_governance(
            procedural=PROCEDURAL_MEMORY,
            semantic=SEMANTIC_MEMORY,
        )

    def compile_graph(self, builder: StateGraph | None = None) -> Any:
        """Compile visibly so a client can inspect the exact builder."""

        self.graph_builder = builder or self.graph_builder
        self.graph = self.graph_builder.compile(
            checkpointer=self.resources.checkpointer,
        )
        return self.graph

    def graph_mermaid(self) -> str:
        if self.graph is None:
            raise RuntimeError("Compile the graph before rendering it")
        return self.graph.get_graph().draw_mermaid()

    def _event(
        self, thread_id: str, event_type: str, **details: Any
    ) -> dict[str, Any]:
        event = {
            "event_id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "event_type": event_type,
            "timestamp": utcnow(),
            "details": json_safe(details),
        }
        self.agent_memory.record_event(event)
        return event

    def _execute_once(
        self,
        state: WorkflowState,
        operation: str,
        producer: Callable[[], dict[str, Any]],
    ) -> OperationResult:
        """Reconcile an operation independently of the following graph checkpoint."""

        thread_id = state["thread_id"]
        key = stable_hash(
            {
                "tenant": self.settings.tenant_id,
                "thread": thread_id,
                "case": state["case_id"],
                "operation": operation,
            }
        )
        existing = self.ledger.get(
            self.application,
            "working",
            key,
            scope=(thread_id, "operations"),
        )
        if existing is not None:
            self._event(
                thread_id,
                "idempotent_replay",
                operation=operation,
                idempotency_key=key,
            )
            return OperationResult(
                value=dict(existing["result"]), reused=True, key=key
            )

        value = json_safe(producer())
        self.ledger.put(
            self.application,
            "working",
            {
                "operation": operation,
                "idempotency_key": key,
                "result": value,
                "committed_at": utcnow(),
            },
            key=key,
            scope=(thread_id, "operations"),
        )
        self._event(
            thread_id,
            "operation_committed",
            operation=operation,
            idempotency_key=key,
        )

        if state.get("fail_once_at") == operation:
            fault_key = f"fault:{key}"
            consumed = self.ledger.get(
                self.application,
                "working",
                fault_key,
                scope=(thread_id, "faults"),
            )
            if consumed is None:
                self.ledger.put(
                    self.application,
                    "working",
                    {
                        "operation": operation,
                        "consumed_at": utcnow(),
                        "reason": "requested_failure_after_commit",
                    },
                    key=fault_key,
                    scope=(thread_id, "faults"),
                )
                self._event(
                    thread_id,
                    "fault_injected",
                    operation=operation,
                    recoverable=True,
                )
                raise RuntimeError(
                    f"Simulated crash after {operation!r} committed. Resume the same thread."
                )
        return OperationResult(value=value, reused=False, key=key)

    @staticmethod
    def _idempotency_entry(operation: str, result: OperationResult) -> dict[str, Any]:
        return {
            "operation": operation,
            "idempotency_key": result.key,
            "reused": result.reused,
        }

    def _run_tool(
        self,
        state: WorkflowState,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> OperationResult:
        if tool_name not in state.get("selected_tools", []):
            raise PermissionError(
                f"Tool {tool_name!r} is not in the semantically retrieved, skill-authorized subset"
            )
        return self._execute_once(
            state,
            f"tool:{tool_name}",
            lambda: self.tool_executor.execute(tool_name, arguments),
        )

    def build_graph(self) -> StateGraph:
        """Build the full graph; compilation is a separate, inspectable step."""

        builder = StateGraph(WorkflowState)

        def load_context(state: WorkflowState) -> dict[str, Any]:
            thread_id = state["thread_id"]
            context = self.agent_memory.recall_context(
                thread_id, state["objective"]
            )
            context["working"] = {
                "objective": state["objective"],
                "requested_by": state["requested_by"],
            }
            return {
                "context": context,
                "audit": [
                    self._event(
                        thread_id,
                        "memory_recalled",
                        memory_types=["working", "procedural-routing", "semantic"],
                    )
                ],
            }

        def retrieve_skills(state: WorkflowState) -> dict[str, Any]:
            rows = self.catalog.retrieve_skills(state["objective"], k=5)
            manifest = "\n".join(
                f"- {row['name']}: {row['description']} [sha:{row['sha'][:12]}]"
                for row in rows
            )
            return {
                "skill_candidates": rows,
                "skill_manifest": manifest,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "skills_retrieved",
                        level=1,
                        names=[row["name"] for row in rows],
                    )
                ],
            }

        def plan_review(state: WorkflowState) -> dict[str, Any]:
            result = self._execute_once(
                state,
                "plan_review",
                lambda: self.model_provider.plan(
                    objective=state["objective"],
                    skill_manifest=state["skill_manifest"],
                    skill_candidates=state["skill_candidates"],
                ),
            )
            loaded = []
            for name in result.value["selected_skills"]:
                skill = self.catalog.load_skill(name)
                if "error" in skill:
                    raise RuntimeError(f"Planner selected unknown skill {name!r}")
                loaded.append(skill)
            return {
                "plan": result.value,
                "loaded_skills": loaded,
                "idempotency": [self._idempotency_entry("plan_review", result)],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "skills_loaded",
                        level=2,
                        names=[item["name"] for item in loaded],
                        shas=[item["sha"] for item in loaded],
                        reused=result.reused,
                    )
                ],
            }

        def retrieve_tools(state: WorkflowState) -> dict[str, Any]:
            authorized = []
            for skill in state["loaded_skills"]:
                for name in skill["tools_used"]:
                    if name not in authorized:
                        authorized.append(name)
            query = state["plan"]["tool_query"] + " " + " ".join(authorized)
            rows = self.catalog.retrieve_tools(query, k=8)
            retrieved_names = {row["name"] for row in rows}
            missing = sorted(set(authorized) - retrieved_names)
            if missing:
                raise RuntimeError(
                    "Semantic toolbox did not retrieve required skill tools: "
                    + ", ".join(missing)
                )
            selected = [row["name"] for row in rows if row["name"] in authorized]
            return {
                "tool_candidates": rows,
                "selected_tools": selected,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "tools_retrieved",
                        candidates=[row["name"] for row in rows],
                        selected=selected,
                    )
                ],
            }

        def collect_case(state: WorkflowState) -> dict[str, Any]:
            result = self._run_tool(
                state,
                tool_name="load_supplier_case",
                arguments={"case_id": state["case_id"]},
            )
            envelope = result.value
            case = envelope["output"]["result"]
            if "error" in case:
                raise RuntimeError(case["error"])
            return {
                "source_case": case,
                "sandbox_trace": [envelope],
                "idempotency": [self._idempotency_entry("tool:load_supplier_case", result)],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "case_loaded",
                        supplier_id=case["supplier"]["supplier_id"],
                        sandbox_provider=envelope["execution"]["provider"],
                        reused=result.reused,
                    )
                ],
            }

        def validate_evidence(state: WorkflowState) -> dict[str, Any]:
            result = self._run_tool(
                state,
                tool_name="validate_evidence_freshness",
                arguments={
                    "controls": state["source_case"]["controls"],
                    "maximum_age_days": 365,
                },
            )
            envelope = result.value
            value = envelope["output"]["result"]
            return {
                "freshness_result": value,
                "findings": list(value["findings"]),
                "sandbox_trace": [envelope],
                "idempotency": [
                    self._idempotency_entry("tool:validate_evidence_freshness", result)
                ],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "evidence_validated",
                        blocking=value["blocking_control_ids"],
                        reused=result.reused,
                    )
                ],
            }

        def screen_sanctions(state: WorkflowState) -> dict[str, Any]:
            result = self._run_tool(
                state,
                tool_name="screen_supplier_sanctions",
                arguments={
                    "supplier": state["source_case"]["supplier"],
                    "screening_record": state["source_case"]["sanctions_screening"],
                },
            )
            envelope = result.value
            value = envelope["output"]["result"]
            return {
                "sanctions_result": value,
                "sandbox_trace": [envelope],
                "idempotency": [
                    self._idempotency_entry("tool:screen_supplier_sanctions", result)
                ],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "sanctions_screened",
                        status=value["status"],
                        screening_id=value["screening_id"],
                        reused=result.reused,
                    )
                ],
            }

        def assess_risk(state: WorkflowState) -> dict[str, Any]:
            result = self._run_tool(
                state,
                tool_name="calculate_supplier_risk",
                arguments={
                    "supplier": state["source_case"]["supplier"],
                    "freshness_result": state["freshness_result"],
                    "sanctions_result": state["sanctions_result"],
                },
            )
            envelope = result.value
            value = envelope["output"]["result"]
            return {
                "risk_assessment": value,
                "sandbox_trace": [envelope],
                "idempotency": [
                    self._idempotency_entry("tool:calculate_supplier_risk", result)
                ],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "risk_assessed",
                        score=value["score"],
                        route=value["route"],
                        reused=result.reused,
                    )
                ],
            }

        def build_remediation(state: WorkflowState) -> dict[str, Any]:
            result = self._run_tool(
                state,
                tool_name="build_remediation_plan",
                arguments={
                    "supplier_id": state["source_case"]["supplier"]["supplier_id"],
                    "findings": state["freshness_result"]["findings"],
                },
            )
            envelope = result.value
            value = envelope["output"]["result"]
            return {
                "remediation_plan": value,
                "sandbox_trace": [envelope],
                "idempotency": [
                    self._idempotency_entry("tool:build_remediation_plan", result)
                ],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "remediation_built",
                        actions=len(value["actions"]),
                        reused=result.reused,
                    )
                ],
            }

        def draft_report(state: WorkflowState) -> dict[str, Any]:
            result = self._execute_once(
                state,
                "draft_report",
                lambda: self.model_provider.draft(
                    source_case=state["source_case"],
                    context=state["context"],
                    freshness_result=state["freshness_result"],
                    sanctions_result=state["sanctions_result"],
                    risk_assessment=state["risk_assessment"],
                    remediation_plan=state["remediation_plan"],
                    loaded_skills=state["loaded_skills"],
                ),
            )
            return {
                "draft": result.value,
                "idempotency": [self._idempotency_entry("draft_report", result)],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "draft_ready",
                        report_id=result.value["report_id"],
                        risk=result.value["risk"],
                        model_provider=self.model_provider.status()["provider"],
                        reused=result.reused,
                    )
                ],
            }

        def approval_gate(state: WorkflowState) -> dict[str, Any]:
            proposal = {
                "action": "publish_compliance_report",
                "thread_id": state["thread_id"],
                "report_id": state["draft"]["report_id"],
                "risk": state["draft"]["risk"],
                "blocking_findings": [
                    item
                    for item in state["draft"]["findings"]
                    if item["severity"] == "blocking"
                ],
                "remediation_actions": state["remediation_plan"]["actions"],
                "argument_hash": stable_hash(
                    {
                        "thread_id": state["thread_id"],
                        "report": state["draft"],
                        "action": "publish_compliance_report",
                    }
                ),
                "instruction": "A named human owner must approve or reject this exact draft.",
            }
            decision = interrupt(proposal)
            if not isinstance(decision, Mapping):
                raise ValueError("Approval resume value must be an object")
            approved = bool(decision.get("approved"))
            approval = {
                **proposal,
                "approved": approved,
                "decided_by": str(decision.get("decided_by") or "unknown-host"),
                "comment": str(decision.get("comment") or ""),
                "decided_at": utcnow(),
            }
            return {
                "approval": approval,
                "audit": [
                    self._event(
                        state["thread_id"],
                        "approval_decided",
                        approved=approved,
                        decided_by=approval["decided_by"],
                        argument_hash=proposal["argument_hash"],
                    )
                ],
            }

        def route_approval(state: WorkflowState) -> str:
            return "publish" if state.get("approval", {}).get("approved") else "reject"

        def publish(state: WorkflowState) -> dict[str, Any]:
            result = self._execute_once(
                state,
                "publish_report",
                lambda: {
                    "publication_id": f"PUB-{state['draft']['report_id']}",
                    "report": state["draft"],
                    "approval": state["approval"],
                    "published_at": utcnow(),
                    "immutable_digest": stable_hash(state["draft"]),
                },
            )
            self.agent_memory.record_outcome(
                state["thread_id"], state["draft"], result.value
            )
            return {
                "publication": result.value,
                "outcome": "published",
                "idempotency": [self._idempotency_entry("publish_report", result)],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "report_published",
                        publication_id=result.value["publication_id"],
                        reused=result.reused,
                    )
                ],
            }

        def reject(state: WorkflowState) -> dict[str, Any]:
            return {
                "outcome": "rejected",
                "audit": [
                    self._event(
                        state["thread_id"],
                        "publication_rejected",
                        decided_by=state.get("approval", {}).get("decided_by"),
                    )
                ],
            }

        def verify_result(state: WorkflowState) -> dict[str, Any]:
            result = self._run_tool(
                state,
                tool_name="verify_report_package",
                arguments={"publication": state["publication"]},
            )
            envelope = result.value
            verification = envelope["output"]["result"]
            if not verification.get("verified"):
                raise RuntimeError("Published report package failed host verification")
            return {
                "verification": verification,
                "sandbox_trace": [envelope],
                "idempotency": [
                    self._idempotency_entry("tool:verify_report_package", result)
                ],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "publication_verified",
                        checks=verification["checks"],
                        reused=result.reused,
                    )
                ],
            }

        def capture_workflow(state: WorkflowState) -> dict[str, Any]:
            successful = bool(
                state.get("outcome") == "published"
                and state.get("verification", {}).get("verified")
            )
            node_names = [
                "load_context",
                "retrieve_skills",
                "plan_review",
                "retrieve_tools",
                "collect_case",
                "validate_evidence",
                "screen_sanctions",
                "assess_risk",
                "build_remediation",
                "draft_report",
                "approval_gate",
                "publish" if successful else "reject",
            ]
            if successful:
                node_names.append("verify_result")
            steps = [{"node": name} for name in node_names]
            tools = [item["tool"] for item in state.get("sandbox_trace", [])]
            result = self._execute_once(
                state,
                "capture_workflow",
                lambda: self.catalog.capture_workflow(
                    intent=state["objective"],
                    steps=steps,
                    tools_used=tools,
                    success=successful,
                ),
            )
            return {
                "workflow_recipe": result.value,
                "idempotency": [self._idempotency_entry("capture_workflow", result)],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "workflow_captured",
                        recipe_id=result.value["recipe_id"],
                        success=successful,
                        occurrences=result.value["occurrences"],
                        reused=result.reused,
                    )
                ],
            }

        def promote_skill(state: WorkflowState) -> dict[str, Any]:
            result = self._execute_once(
                state,
                "promote_workflow_skill",
                lambda: self.promoter.promote(state["workflow_recipe"]["recipe_id"]),
            )
            return {
                "promotion": result.value,
                "idempotency": [
                    self._idempotency_entry("promote_workflow_skill", result)
                ],
                "audit": [
                    self._event(
                        state["thread_id"],
                        "skill_promotion_evaluated",
                        status=result.value.get("status"),
                        skill_name=result.value.get("skill_name"),
                        reused=result.reused,
                    )
                ],
            }

        builder.add_node("load_context", load_context)
        builder.add_node("retrieve_skills", retrieve_skills)
        builder.add_node("plan_review", plan_review)
        builder.add_node("retrieve_tools", retrieve_tools)
        builder.add_node("collect_case", collect_case)
        builder.add_node("validate_evidence", validate_evidence)
        builder.add_node("screen_sanctions", screen_sanctions)
        builder.add_node("assess_risk", assess_risk)
        builder.add_node("build_remediation", build_remediation)
        builder.add_node("draft_report", draft_report)
        builder.add_node("approval_gate", approval_gate)
        builder.add_node("publish", publish)
        builder.add_node("reject", reject)
        builder.add_node("verify_result", verify_result)
        builder.add_node("capture_workflow", capture_workflow)
        builder.add_node("promote_skill", promote_skill)
        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "retrieve_skills")
        builder.add_edge("retrieve_skills", "plan_review")
        builder.add_edge("plan_review", "retrieve_tools")
        builder.add_edge("retrieve_tools", "collect_case")
        builder.add_edge("collect_case", "validate_evidence")
        builder.add_edge("validate_evidence", "screen_sanctions")
        builder.add_edge("screen_sanctions", "assess_risk")
        builder.add_edge("assess_risk", "build_remediation")
        builder.add_edge("build_remediation", "draft_report")
        builder.add_edge("draft_report", "approval_gate")
        builder.add_conditional_edges(
            "approval_gate", route_approval, {"publish": "publish", "reject": "reject"}
        )
        builder.add_edge("publish", "verify_result")
        builder.add_edge("verify_result", "capture_workflow")
        builder.add_edge("reject", "capture_workflow")
        builder.add_edge("capture_workflow", "promote_skill")
        builder.add_edge("promote_skill", END)
        return builder

    def _build_graph(self) -> StateGraph:
        return self.build_graph()

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def _require_compiled(self) -> None:
        if self.graph is None:
            raise RuntimeError("The LangGraph builder has not been compiled")

    def start(
        self,
        *,
        thread_id: str | None = None,
        fail_once_at: str = "draft_report",
        requested_by: str | None = None,
        objective: str | None = None,
    ) -> dict[str, Any]:
        self._require_compiled()
        resolved_thread = thread_id or f"compliance-{uuid.uuid4().hex[:10]}"
        initial: WorkflowState = {
            "thread_id": resolved_thread,
            "case_id": "SUP-1042:2026-Q3",
            "objective": objective or (
                "Review the high-risk supplier, validate evidence and sanctions, "
                "score risk, build remediation, obtain a named decision, publish once, "
                "verify the package, and learn only from a recurring successful path."
            ),
            "requested_by": requested_by or self.settings.user_id,
            "fail_once_at": fail_once_at,
            "sandbox_trace": [],
            "audit": [],
            "idempotency": [],
        }
        return self._invoke(initial, resolved_thread, action="start")

    def resume_after_failure(self, thread_id: str) -> dict[str, Any]:
        self._require_compiled()
        return self._invoke(None, thread_id, action="resume_after_failure")

    def decide(
        self,
        thread_id: str,
        *,
        approved: bool,
        decided_by: str,
        comment: str = "",
    ) -> dict[str, Any]:
        self._require_compiled()
        command = Command(
            resume={
                "approved": bool(approved),
                "decided_by": decided_by,
                "comment": comment,
            }
        )
        return self._invoke(command, thread_id, action="approval_resume")

    def _invoke(
        self, value: Any, thread_id: str, *, action: str
    ) -> dict[str, Any]:
        self._latest_thread_id = thread_id
        config = self._config(thread_id)
        with self._lock:
            try:
                self.graph.invoke(value, config=config)
                self._last_errors.pop(thread_id, None)
            except Exception as exc:
                error = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "action": action,
                    "timestamp": utcnow(),
                }
                self._last_errors[thread_id] = error
                return {**self.inspect(thread_id), "error": error}
        return self.inspect(thread_id)

    def inspect(self, thread_id: str) -> dict[str, Any]:
        self._require_compiled()
        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        values = json_safe(dict(snapshot.values or {}))
        interrupts: list[dict[str, Any]] = []
        for task in snapshot.tasks or ():
            for item in getattr(task, "interrupts", ()) or ():
                interrupts.append(json_safe(getattr(item, "value", item)))
        if interrupts:
            status = "pending_approval"
        elif snapshot.next:
            status = "resumable"
        elif values.get("outcome"):
            status = values["outcome"]
        elif values:
            status = "complete"
        else:
            status = "not_found"
        history = []
        if values:
            for item in list(self.graph.get_state_history(config))[:50]:
                history.append(
                    {
                        "created_at": str(item.created_at or ""),
                        "next": list(item.next or ()),
                        "step": (item.metadata or {}).get("step"),
                        "source": (item.metadata or {}).get("source"),
                    }
                )
        episodic_audit = self.agent_memory.events(thread_id)
        last_error = self._last_errors.get(thread_id)
        return {
            "thread_id": thread_id,
            "status": status,
            "next": list(snapshot.next or ()),
            "interrupts": interrupts,
            "state": values,
            "checkpoint_history": history,
            "episodic_audit": episodic_audit,
            "workflow_view": self._workflow_view(
                values=values,
                next_nodes=list(snapshot.next or ()),
                run_status=status,
                last_error=last_error,
                audit=episodic_audit,
            ),
            "last_error": last_error,
            "persistence": {
                "backend": self.resources.backend,
                "oracle_version": self.resources.oracle_version,
                "checkpointer": type(self.resources.checkpointer).__name__,
                "operation_ledger": type(self.resources.store).__name__,
                "agent_memory": self.agent_memory.status(),
                "catalog": self.catalog.status(),
                "sandbox": self.tool_executor.status(),
                "promotion": self.promoter.status(),
            },
        }

    def context_window(self) -> dict[str, Any]:
        """Expose the assembled, model-visible context—not private reasoning."""

        model = self.model_provider.status()
        state: dict[str, Any] = {}
        phase = "awaiting_run"
        if self._latest_thread_id:
            inspected = self.inspect(self._latest_thread_id)
            state = dict(inspected.get("state") or {})
            phase = str(inspected.get("status") or "running")
        objective = state.get("objective") or self.status()["use_case"]["objective"]
        sections = [
            {
                "title": "Harness policy",
                "kind": "system",
                "source": "host policy",
                "content": (
                    "Plan and draft with the model; establish facts with authorized "
                    "sandboxed tools; preserve source identifiers; pause before "
                    "publication; verify every side effect in the host."
                ),
            },
            {"title": "Operator objective", "kind": "user", "content": objective},
            {
                "title": "Oracle Agent Memory context card",
                "kind": "memory",
                "source": "Oracle Agent Memory",
                "content": state.get("context") or {"status": "not retrieved yet"},
            },
            {
                "title": "Skill manifest (level 1)",
                "kind": "skill manifest",
                "source": "semantic Skillbox",
                "content": state.get("skill_manifest") or "(retrieved at run time)",
            },
            {
                "title": "Loaded SKILL.md bodies (level 2)",
                "kind": "skills",
                "source": "semantic Skillbox",
                "content": state.get("loaded_skills") or [],
            },
            {
                "title": "Bound tool contracts",
                "kind": "tools",
                "source": "semantic Toolbox",
                "content": {
                    "selected_tools": state.get("selected_tools") or [],
                    "candidates": state.get("tool_candidates") or [],
                },
            },
            {
                "title": "Verified working state",
                "kind": "evidence",
                "source": "sandbox outputs + host checks",
                "content": {
                    key: state.get(key)
                    for key in (
                        "source_case",
                        "freshness_result",
                        "sanctions_result",
                        "risk_assessment",
                        "remediation_plan",
                        "draft",
                    )
                    if state.get(key) is not None
                },
            },
        ]
        return context_window(
            sections,
            provider=str(model.get("provider") or model.get("model_provider") or "none"),
            model=str(model.get("model") or "none"),
            phase=phase,
            actual_model_call=bool(model.get("model_backed") and state),
            max_tokens=32_000,
            note="Planning and drafting use separately assembled subsets of these visible sections.",
        )

    @classmethod
    def _workflow_view(
        cls,
        *,
        values: Mapping[str, Any] | None = None,
        next_nodes: list[str] | None = None,
        run_status: str = "not_started",
        last_error: Mapping[str, Any] | None = None,
        audit: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return full topology plus checkpoint-derived node and edge status."""

        state = dict(values or {})
        next_set = set(next_nodes or [])
        node_status = {item["id"]: "pending" for item in cls.workflow_nodes}
        node_status["start"] = "completed" if state else "ready"
        completion_keys = {
            "load_context": "context",
            "retrieve_skills": "skill_candidates",
            "plan_review": "plan",
            "retrieve_tools": "selected_tools",
            "collect_case": "source_case",
            "validate_evidence": "freshness_result",
            "screen_sanctions": "sanctions_result",
            "assess_risk": "risk_assessment",
            "build_remediation": "remediation_plan",
            "draft_report": "draft",
            "approval_gate": "approval",
            "verify_result": "verification",
            "capture_workflow": "workflow_recipe",
            "promote_skill": "promotion",
        }
        for node_id, key in completion_keys.items():
            if state.get(key):
                node_status[node_id] = "completed"
        if state.get("outcome") == "published":
            node_status["publish"] = "completed"
            node_status["reject"] = "skipped"
        elif state.get("outcome") == "rejected":
            node_status["reject"] = "completed"
            node_status["publish"] = "skipped"
            node_status["verify_result"] = "skipped"
        if run_status == "pending_approval":
            node_status["approval_gate"] = "paused"
        if state.get("promotion") and not next_set:
            node_status["end"] = "completed"
        for node_id in next_set:
            if node_status.get(node_id) == "pending":
                node_status[node_id] = "ready"
        if last_error and next_set:
            node_status[sorted(next_set)[0]] = "failed"

        details = {
            "start": "request accepted" if state else "awaiting a run",
            "load_context": "Oracle Agent Memory context and routing rule",
            "retrieve_skills": "semantic level-1 manifest retrieval (HNSW when available)",
            "plan_review": "model selects skills; harness loads full SKILL.md bodies",
            "retrieve_tools": "semantic top-k JSON tool contracts (HNSW when available)",
            "collect_case": "fresh sandbox: authoritative case input → execution → output",
            "validate_evidence": "fresh sandbox: 365-day policy and preserved evidence IDs",
            "screen_sanctions": "fresh sandbox: authoritative screening record",
            "assess_risk": "fresh sandbox: explainable deterministic score",
            "build_remediation": "fresh sandbox: owned corrective actions",
            "draft_report": (
                "operation committed; graph return failed before checkpoint"
                if node_status["draft_report"] == "failed"
                else "model draft grounded against verified data"
            ),
            "approval_gate": "exact report digest paused for a named human",
            "publish": "idempotent publication side effect",
            "reject": "terminal rejection branch",
            "verify_result": "fresh sandbox plus host recomputation",
            "capture_workflow": "typed recipe with occurrences, successes, and failures",
            "promote_skill": "eligible recipe → SHA-versioned SKILL.md",
            "end": "terminal checkpoint",
        }
        nodes = [
            {**item, "status": node_status[item["id"]], "detail": details[item["id"]]}
            for item in cls.workflow_nodes
        ]

        traversed_pairs: set[tuple[str, str]] = set()
        for edge in cls.workflow_edges:
            target_status = node_status[edge["target"]]
            source_status = node_status[edge["source"]]
            if target_status in {"completed", "paused", "ready", "failed"} and source_status == "completed":
                traversed_pairs.add((edge["source"], edge["target"]))
        edges = []
        for edge in cls.workflow_edges:
            pair = (edge["source"], edge["target"])
            target_status = node_status[edge["target"]]
            edge_status = (
                "skipped"
                if target_status == "skipped"
                else "traversed"
                if pair in traversed_pairs
                else "pending"
            )
            edges.append({**edge, "status": edge_status})

        event_nodes = {
            "memory_recalled": "load_context",
            "skills_retrieved": "retrieve_skills",
            "skills_loaded": "plan_review",
            "tools_retrieved": "retrieve_tools",
            "case_loaded": "collect_case",
            "evidence_validated": "validate_evidence",
            "sanctions_screened": "screen_sanctions",
            "risk_assessed": "assess_risk",
            "remediation_built": "build_remediation",
            "draft_ready": "draft_report",
            "approval_decided": "approval_gate",
            "report_published": "publish",
            "publication_rejected": "reject",
            "publication_verified": "verify_result",
            "workflow_captured": "capture_workflow",
            "skill_promotion_evaluated": "promote_skill",
        }
        operation_nodes = {
            "plan_review": "plan_review",
            "tool:load_supplier_case": "collect_case",
            "tool:validate_evidence_freshness": "validate_evidence",
            "tool:screen_supplier_sanctions": "screen_sanctions",
            "tool:calculate_supplier_risk": "assess_risk",
            "tool:build_remediation_plan": "build_remediation",
            "draft_report": "draft_report",
            "publish_report": "publish",
            "tool:verify_report_package": "verify_result",
            "capture_workflow": "capture_workflow",
            "promote_workflow_skill": "promote_skill",
        }
        trace = []
        for item in sorted(audit or [], key=lambda event: str(event.get("timestamp", ""))):
            event_type = str(item.get("event_type", "event"))
            details_value = dict(item.get("details") or {})
            node_id = event_nodes.get(event_type)
            if node_id is None and event_type in {
                "operation_committed",
                "fault_injected",
                "idempotent_replay",
            }:
                node_id = operation_nodes.get(str(details_value.get("operation") or ""))
            trace.append(
                {
                    "event_type": event_type,
                    "node_id": node_id,
                    "timestamp": item.get("timestamp"),
                    "details": json_safe(details_value),
                }
            )
        return {
            "run_status": run_status,
            "nodes": nodes,
            "edges": edges,
            "active_node_ids": [
                node_id
                for node_id, value in node_status.items()
                if value in {"ready", "paused", "failed"}
            ],
            "trace": trace,
        }

    def status(self) -> dict[str, Any]:
        agent_memory = self.agent_memory.status()
        model = self.model_provider.status()
        catalog = self.catalog.status()
        return {
            "ready": True,
            "section": "workflow",
            "architecture": "LLM-planned durable graph inside a governed agent harness",
            "use_case": {
                "case_id": "SUP-1042:2026-Q3",
                "supplier": "Northstar Textiles (synthetic)",
                "objective": (
                    "Complete intake, evidence freshness, sanctions, risk, remediation, "
                    "drafting, named approval, exactly-once publication, verification, "
                    "and reliable workflow-to-skill learning."
                ),
                "business_context": (
                    "The supplier is production-critical with $4.8M annual spend. Its "
                    "restricted-substance certificate is 401 days old and an audit "
                    "remediation remains open."
                ),
                "decision": (
                    "The model plans and drafts; deterministic tools establish facts; "
                    "a named compliance owner alone decides publication."
                ),
            },
            "nodes": [item["id"] for item in self.workflow_nodes if item["kind"] != "boundary"],
            "workflow_view": self._workflow_view(),
            "memory_types": agent_memory["record_types"],
            "providers": {
                "orchestrator": "LangGraph StateGraph",
                "checkpointer": type(self.resources.checkpointer).__name__,
                "memory_manager": agent_memory["provider"],
                "memory_substrate": agent_memory["substrate"],
                "operation_ledger": type(self.resources.store).__name__,
                "generation_model": {**model, "active": model["model_backed"]},
                "embedding_model": {
                    "provider": catalog["embedding_provider"],
                    "model": catalog["embedding_model"],
                    "dimensions": catalog["dimensions"],
                    "active": True,
                },
                "toolbox": {
                    "table": "ADV_AGENT_TOOLS",
                    "retrieval": catalog["retrieval"],
                    "index": catalog["index"],
                    "callables": "Python TOOL_REGISTRY",
                },
                "skillbox": {
                    "table": "ADV_AGENT_SKILLS",
                    "format": "SKILL.md + SHA-256",
                    "retrieval": "level-1 semantic manifest; level-2 exact full-body load",
                },
                "workflow_memory": {
                    "table": "ADV_WORKFLOW_RECIPES",
                    **self.promoter.status(),
                },
                "sandbox": self.tool_executor.status(),
            },
            "settings": self.settings.public_status(),
            "persistence": {
                "backend": self.resources.backend,
                "oracle_version": self.resources.oracle_version,
                "checkpointer": type(self.resources.checkpointer).__name__,
                "operation_ledger": type(self.resources.store).__name__,
                "agent_memory": agent_memory,
                "catalog": catalog,
            },
        }

    def close(self) -> None:
        try:
            self.agent_memory.close()
        finally:
            if self._owns_resources:
                self.resources.close()


_runtime: WorkflowHarness | None = None
_runtime_lock = threading.RLock()


def get_workflow_harness() -> WorkflowHarness:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = WorkflowHarness()
        return _runtime


__all__ = ["SKILLS_ROOT", "WorkflowHarness", "WorkflowState", "get_workflow_harness"]
