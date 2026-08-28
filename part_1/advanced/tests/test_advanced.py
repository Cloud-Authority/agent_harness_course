"""Acceptance tests for the advanced Part 1 course material."""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import nbformat
import pytest
from fastapi.testclient import TestClient


os.environ["ADVANCED_BACKEND"] = "memory"
os.environ["ADVANCED_SEMANTIC_BACKEND"] = "hash"
os.environ["ADVANCED_RESEARCH_SOURCE"] = "fixture"
os.environ["ADVANCED_USE_MODEL_SYNTHESIS"] = "false"
os.environ["ADVANCED_NOTEBOOK_LIVE"] = "0"
os.environ["ADVANCED_SANDBOX_LIVE"] = "0"
os.environ["ADVANCED_OPENAI_MODEL"] = "gpt-5.5"
os.environ["ADVANCED_ANTHROPIC_MODEL"] = "claude-opus-5"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""
os.environ["E2B_API_KEY"] = ""

from part_1.advanced.shared.fixtures import PROCEDURAL_MEMORY, SEMANTIC_MEMORY, compliance_case
from part_1.advanced.shared.live_model_harness import LiveModelHarness
from part_1.advanced.shared.model_provider import OpenAIResponsesComplianceDrafter
from part_1.advanced.shared.research import DeepResearchHarness, ResearchConfig
from part_1.advanced.shared.security import public_error
from part_1.advanced.shared.workflow import WorkflowHarness
from part_1.advanced.shared.total_recall import TotalRecallHarness


ADVANCED = Path(__file__).resolve().parents[1]


def test_public_errors_redact_runtime_credentials(monkeypatch) -> None:
    secret = "synthetic-secret-value-for-redaction"
    monkeypatch.setenv("SYNTHETIC_API_KEY", secret)
    rendered = public_error(RuntimeError(f"provider rejected {secret}"))
    assert secret not in rendered
    assert "<redacted>" in rendered


def test_deepseek_harness_uses_current_chat_api_shape() -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[])

    harness = LiveModelHarness(
        name="deepseek-live",
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key="synthetic-deepseek-credential-value",
        base_url="https://api.deepseek.com/",
    )
    harness._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    harness._deepseek("bounded incident context", 4000)

    assert harness.probe().available is True
    assert harness.base_url == "https://api.deepseek.com"
    assert calls == [
        {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": calls[0]["messages"][0]["content"]},
                {"role": "user", "content": "bounded incident context"},
            ],
            "max_tokens": 4000,
            "stream": False,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    ]


class _FakeStructuredResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "risk": "blocked_pending_remediation",
                    "findings": [
                        {
                            "control_id": item["control_id"],
                            "evidence_id": item["evidence_id"],
                            "status": item["status"],
                            "severity": (
                                "blocking"
                                if item["status"] == "expired"
                                else "material"
                                if item["status"] == "open"
                                else "clear"
                            ),
                        }
                        for item in compliance_case()["controls"]
                    ],
                    "recommendation": "Require a replacement certificate and named owner.",
                }
            )
        )


class _FakeStructuredOpenAI:
    def __init__(self) -> None:
        self.responses = _FakeStructuredResponses()


def test_published_package_provenance_and_notebook_quality() -> None:
    import memorizz

    assert version("memorizz") == "0.6.3"
    assert version("oracleagentmemory") == "26.6.0"
    assert version("anthropic") == "1.0.0"
    assert version("e2b") == "2.37.1"
    assert version("e2b-code-interpreter") == "2.9.0"
    assert "site-packages" in str(Path(memorizz.__file__).resolve())

    notebooks = sorted(ADVANCED.glob("*/notebook/*.ipynb"))
    assert len(notebooks) == 5
    for path in notebooks:
        notebook = nbformat.read(path, as_version=4)
        markdown = "\n".join(
            cell.source for cell in notebook.cells if cell.cell_type == "markdown"
        )
        if path.name == "advanced_metaharness.ipynb":
            source = "\n".join(cell.source for cell in notebook.cells)
            assert markdown.count("```mermaid") >= 1
            assert len(markdown.split()) >= 1_800
            assert "the production use case: ai-operations incident triage" in markdown.lower()
            assert "you might want a meta harness" in markdown.lower()
            assert "OracleHarnessRunStore" in source
            assert "OracleApprovalStore" in source
            assert "LiveModelHarness" in source
            assert "HarnessContextBuilder" in source
            assert "AI-operations incident triage" in source
            assert "deepseek-live" in source
            assert "deepseek-v4-flash" in source
            assert "SOURCE_OBJECTS" not in source
            assert "source_map" not in source
            assert "Index the code you are actually studying" not in source
            assert "input(\"Live question:" in source
            assert not re.search(
                r"sqlite|fixture|test double|deterministic adapter|\bcontract\b",
                source,
                re.IGNORECASE,
            )
            code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
            for index, cell in enumerate(notebook.cells):
                if cell.cell_type == "code":
                    compile(cell.source, f"{path}#cell-{index}", "exec")
            assert all(cell.execution_count is not None for cell in code_cells)
            outputs = [
                output
                for cell in code_cells
                for output in cell.get("outputs", [])
            ]
            assert outputs
            assert all(output.output_type != "error" for output in outputs)
            rendered_outputs = json.dumps(outputs, default=str)
            assert "'status': 'succeeded'" in rendered_outputs
            assert "'selected': 'openai-live'" in rendered_outputs
            assert not any(
                marker in rendered_outputs
                for marker in ("sk-" + "proj-", "sk-" + "ant-api")
            )
            continue
        assert markdown.count("```mermaid") >= 4
        assert len(markdown.split()) >= 800
        if "total_recall" in path.name:
            assert markdown.count("# Part") >= 10
            assert notebook.metadata["harness"]["model"] == "gpt-5.5"
            assert notebook.metadata["harness"]["model_provider"] == "OpenAI Responses API"
        else:
            assert "## Industry use case" in markdown
            assert (
                "## Harness component map" in markdown
                or "## Harness and evaluator component map" in markdown
            )
            assert markdown.count("## Part") >= 5
            assert "References" in markdown
        assert "getpass(" in "\n".join(cell.source for cell in notebook.cells)
    research_path = next(path for path in notebooks if "deep_research" in path.name)
    research_source = nbformat.read(research_path, as_version=4)
    all_sources = "\n".join(cell.source for cell in research_source.cells)
    research_markdown = "\n".join(
        cell.source
        for cell in research_source.cells
        if cell.cell_type == "markdown"
    )
    assert "getpass(" in all_sources
    assert "DeepResearchOrchestrator" in all_sources
    assert "create_deep_research_agent" in all_sources
    assert "ApplicationMode.DEEP_RESEARCH" in all_sources
    assert "TavilyProvider" in all_sources
    assert "OracleProvider" in all_sources
    assert "configure_embeddings" in all_sources
    assert "text-embedding-3-small" in all_sources
    assert "EMBEDDING_DIMENSIONS = 1536" in all_sources
    assert "E2BSandboxProvider" in all_sources
    assert "execute_code" in all_sources
    assert "PRIVATE_MEMORY_IDS" in all_sources
    assert "shared_memory_id" in all_sources
    assert "build_and_save" in all_sources
    assert "gpt-5.5" in all_sources
    assert '"profile": "live-only"' in all_sources
    assert "ADVANCED_RESEARCH_CONFIRMATION" in all_sources
    assert "part_1.advanced.shared.research" not in all_sources
    for forbidden in (
        "MetaHarness",
        "AgentHarness",
        "NotebookResearchHarness",
        "langgraph",
        "sqlite",
        "fixture",
        "FileSystemProvider",
        "claude",
        "anthropic",
    ):
        assert forbidden.lower() not in all_sources.lower()
    assert re.search(r"\bcontract\b", all_sources, re.IGNORECASE) is None
    assert re.search(r"\bcourse\b", research_markdown, re.IGNORECASE) is None
    for diagram in re.findall(
        r"```mermaid\n(.*?)```", research_markdown, re.DOTALL
    ):
        assert "course" not in diagram.lower()
    research_code_cells = [
        cell for cell in research_source.cells if cell.cell_type == "code"
    ]
    for index, cell in enumerate(research_code_cells):
        compile(cell.source, f"{research_path}#cell-{index}", "exec")
        assert all(
            output.get("output_type") != "error"
            for output in cell.get("outputs", [])
        )
    execution_counts = [cell.get("execution_count") for cell in research_code_cells]
    if any(count is not None for count in execution_counts):
        assert execution_counts == list(range(1, len(research_code_cells) + 1))
        serialized_outputs = json.dumps(
            [cell.get("outputs", []) for cell in research_code_cells]
        )
        for secret_prefix in (
            "sk-" + "proj-",
            "tvly" + "-",
            "e2b" + "_aa",
        ):
            assert secret_prefix not in serialized_outputs
    workflow_path = next(path for path in notebooks if "durable_workflow" in path.name)
    workflow_source = "\n".join(
        cell.source for cell in nbformat.read(workflow_path, as_version=4).cells
    )
    workflow_notebook = nbformat.read(workflow_path, as_version=4)
    workflow_markdown = "\n".join(
        cell.source for cell in workflow_notebook.cells if cell.cell_type == "markdown"
    )
    assert re.search(r"\bcourse\b", workflow_markdown, re.IGNORECASE) is None
    for diagram in re.findall(r"```mermaid\n(.*?)```", workflow_markdown, re.DOTALL):
        assert "notebook" not in diagram.lower()
        assert "appbook" not in diagram.lower()
    assert "TODO" not in workflow_source.upper()
    assert "OracleAgentMemory" in workflow_source
    assert "OracleDBMemoryStore" in workflow_source
    assert "## Part II — write and register the toolbox and Skillbox" in workflow_source
    assert "## Part VI — promote a recurring verified trajectory into a Skill" in workflow_source
    assert "TOOL_REGISTRY" in workflow_source
    assert "def register_tool(" in workflow_source
    assert "def retrieve_tools(" in workflow_source
    assert "def retrieve_skills(" in workflow_source
    assert "def load_skill(" in workflow_source
    assert "high-risk-supplier-review" in workflow_source
    assert "proven-high-risk-supplier-review" in workflow_source
    assert "compiled_graph.get_graph().draw_mermaid()" in workflow_source
    assert "WorkflowHarness" not in workflow_source
    assert "HarnessCatalog" not in workflow_source
    assert "builder.add_edge([\"check_freshness\", \"screen_sanctions\", \"review_audits\"], \"score_risk\")" in workflow_source
    assert "def route_review(" in workflow_source
    assert "def route_after_score(" in workflow_source
    assert "subgraph ORACLE[\"Oracle AI Database\"]" in workflow_source
    assert "ADVANCED_SANDBOX_LIVE" in workflow_source
    assert "envs={}" in workflow_source
    assert "provider.close()" in workflow_source
    assert "def promote_if_eligible(" in workflow_source
    assert all(
        output.output_type != "error"
        for cell in workflow_notebook.cells
        for output in getattr(cell, "outputs", [])
    )
    meta_path = next(path for path in notebooks if "metaharness" in path.name)
    meta_source = "\n".join(
        cell.source for cell in nbformat.read(meta_path, as_version=4).cells
    )
    assert "input(\"Live question:" in meta_source
    assert "openai-live" in meta_source
    assert "anthropic-live" in meta_source
    assert "deepseek-live" in meta_source
    assert "OracleHarnessRunStore" in meta_source
    assert "OracleApprovalStore" in meta_source
    assert "E2BSandboxProvider" not in meta_source
    fair_path = next(path for path in notebooks if "fair_harness" in path.name)
    fair_source = "\n".join(
        cell.source for cell in nbformat.read(fair_path, as_version=4).cells
    )
    assert "paired_factorial_2x6_v1" not in fair_source  # produced by runtime, not hard-coded result data
    assert "getpass(" in fair_source
    assert "winner_allowed" in fair_source
    total_path = next(path for path in notebooks if "total_recall" in path.name)
    total_notebook = nbformat.read(total_path, as_version=4)
    total_source = "\n".join(cell.source for cell in total_notebook.cells)
    total_markdown = "\n".join(
        cell.source for cell in total_notebook.cells if cell.cell_type == "markdown"
    )
    assert len(total_notebook.cells) == 192
    assert len([cell for cell in total_notebook.cells if cell.cell_type == "code"]) == 85
    assert "TotalRecallHarness" not in total_source
    assert "part_1.advanced.shared" not in total_source
    assert "source_url" not in total_notebook.metadata
    assert "source_hash" not in total_notebook.metadata
    assert "openai_client.responses.create" in total_source
    assert '"LLM_MODEL": "gpt-5.5"' in total_source
    assert 'TOOL_REGISTRY[name]["fn"]' in total_source
    assert "ALL_LC_TOOLS" not in total_source
    assert "OracleAgentMemory" in total_source
    assert "class InDatabaseEmbeddings(Embeddings)" in total_source
    assert "OracleEmbeddings" not in total_source
    assert "VECTOR_EMBEDDING" in total_source
    assert "OracleVS" in total_source
    assert "The Memory Substrate" in total_source
    assert "The Semantic Layer" in total_source
    assert "Skills and Automations" in total_source
    assert "DBMS_SCHEDULER" in total_source
    assert "OracleSaver" in total_source
    assert "promote_workflow_to_skill" in total_source
    assert "context_growth.png" in total_source
    assert total_notebook.metadata["harness"]["model_provider"] == "OpenAI Responses API"
    assert total_notebook.metadata["harness"]["model"] == "gpt-5.5"
    for index, cell in enumerate(total_notebook.cells):
        if cell.cell_type == "code":
            tree = ast.parse(
                cell.source,
                filename=f"{total_path}#cell-{index}",
            )
            assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
            compile(cell.source, f"{total_path}#cell-{index}", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    assert all(
        output.output_type != "error"
        for cell in total_notebook.cells
        for output in getattr(cell, "outputs", [])
    )

    repository_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in ADVANCED.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    local_checkout_marker = "/Desktop/" + "memorizz"
    assert local_checkout_marker not in repository_text
    for prefix in (
        "sk-" + "proj-",
        "sk-" + "ant-api",
        "tvly" + "-",
        "e2b" + "_aa",
    ):
        assert prefix not in repository_text


def test_workflow_crash_resume_approval_and_idempotency() -> None:
    harness = WorkflowHarness()
    try:
        thread_id = "pytest-durable-workflow"
        crashed = harness.start(thread_id=thread_id, fail_once_at="draft_report")
        assert crashed["status"] == "resumable"
        assert crashed["next"] == ["draft_report"]
        assert len(crashed["state"]["loaded_skills"]) >= 1
        assert len(crashed["state"]["sandbox_trace"]) == 5
        assert all(
            item["output"]["host_recomputation_matched"]
            and item["execution"]["session_closed"]
            for item in crashed["state"]["sandbox_trace"]
        )
        crashed_nodes = {
            item["id"]: item["status"] for item in crashed["workflow_view"]["nodes"]
        }
        assert crashed_nodes["draft_report"] == "failed"
        assert crashed["workflow_view"]["active_node_ids"] == ["draft_report"]
        pending = harness.resume_after_failure(thread_id)
        assert pending["status"] == "pending_approval"
        pending_nodes = {
            item["id"]: item["status"] for item in pending["workflow_view"]["nodes"]
        }
        assert pending_nodes["approval_gate"] == "paused"
        assert any(
            item["operation"] == "draft_report" and item["reused"]
            for item in pending["state"]["idempotency"]
        )
        completed = harness.decide(
            thread_id,
            approved=True,
            decided_by="pytest-host",
            comment="Exact synthetic report reviewed.",
        )
        assert completed["status"] == "published"
        completed_nodes = {
            item["id"]: item["status"] for item in completed["workflow_view"]["nodes"]
        }
        assert completed_nodes["publish"] == "completed"
        assert completed_nodes["reject"] == "skipped"
        assert completed["state"]["verification"]["verified"] is True
        assert completed["state"]["promotion"]["status"] == "candidate"
        assert len(completed["state"]["sandbox_trace"]) == 6
        assert {
            "fault_injected",
            "idempotent_replay",
            "approval_decided",
            "report_published",
            "publication_verified",
            "workflow_captured",
            "skill_promotion_evaluated",
        } <= {item["event_type"] for item in completed["episodic_audit"]}

        second_thread = "pytest-durable-workflow-second"
        second_pending = harness.start(thread_id=second_thread, fail_once_at="")
        assert second_pending["status"] == "pending_approval"
        second = harness.decide(
            second_thread,
            approved=True,
            decided_by="pytest-host",
            comment="Second verified execution.",
        )
        assert second["status"] == "published"
        assert second["state"]["promotion"]["status"] == "promoted"
        promoted = harness.catalog.load_skill("proven-supplier-compliance-review")
        assert promoted["name"] == "proven-supplier-compliance-review"
        assert len(promoted["sha"]) == 64
        assert "## Steps" in promoted["skill_md"]
    finally:
        harness.close()


def test_openai_drafting_provider_is_wired_and_grounded() -> None:
    client = _FakeStructuredOpenAI()
    drafter = OpenAIResponsesComplianceDrafter(client=client)
    report = drafter.draft(
        source_case=compliance_case(),
        context={"procedural": PROCEDURAL_MEMORY, "semantic": SEMANTIC_MEMORY},
    )
    assert report["risk"] == "blocked_pending_remediation"
    assert report["findings"][1]["evidence_id"] == "EV-219"
    assert client.responses.calls[0]["text"]["format"]["type"] == "json_schema"


def test_memorizz_deep_research_requires_approval_and_verifies_evidence(
    tmp_path: Path,
) -> None:
    config = ResearchConfig.from_env(live=False, data_dir=tmp_path / "research")
    harness = DeepResearchHarness(config=config)
    try:
        before = harness.stack.ledger.cursor()
        pending = harness.start_session(
            "How do durable agent harnesses govern memory, approvals, and research?",
            research_id="pytest-research",
            steering={"focus": "auditable enterprise operations"},
        )
        assert pending["status"] == "pending_approval"
        assert harness.stack.ledger.cursor() == before
        assert pending["approval"]["status"] == "pending"
        assert pending["approval"]["arguments"]["permissions"]["network"] == "none"
        assert pending["approval"]["arguments"]["permissions"]["allowed_tools"] == [
            "internet_search",
            "open_web_page",
        ]

        completed = harness.approve_session(
            pending["checkpoint"]["proposal_id"], approver_id="pytest-owner"
        )
        assert completed["status"] == "succeeded"
        assert completed["verified"] is True
        assert completed["metrics"]["search_requests"] == 4
        assert completed["metrics"]["unique_evidence"] == 8
        assert completed["metrics"]["delegate_count"] == 4
        assert completed["host_checks"]["all_passed"] is True
        assert set(completed["artifact"]["application_modes"].values()) == {
            "deep_research"
        }
        event_types = {item["type"] for item in harness.events(completed["run_id"])}
        assert {"approval", "tool_call", "tool_result", "verification", "complete"} <= event_types
    finally:
        harness.close()


def test_research_fails_closed_before_tools_when_plan_exceeds_budget(
    tmp_path: Path,
) -> None:
    base = ResearchConfig.from_env(live=False, data_dir=tmp_path / "budget")
    harness = DeepResearchHarness(config=replace(base, maximum_steps=3))
    try:
        pending = harness.start_session(
            "Why must a research plan fail closed when it exceeds its host budget?",
            research_id="pytest-fail-closed",
            session_id="session-1",
        )
        completed = harness.approve_session(
            pending["checkpoint"]["proposal_id"], approver_id="pytest-budget-owner"
        )
        assert completed["status"] == "budget_exceeded"
        assert completed["verified"] is False
        assert harness.stack.ledger.cursor() == 0
        assert harness.knowledge("pytest-fail-closed") == []
    finally:
        harness.close()


def test_live_metaharness_is_oracle_only_and_educational() -> None:
    shared = ADVANCED / "shared"
    appbook = ADVANCED / "metaharness" / "appbook"
    paths = [
        shared / "metaharness_demo.py",
        shared / "live_model_harness.py",
        shared / "oracle_harness_stores.py",
        appbook / "backend" / "main.py",
        appbook / "frontend" / "app.js",
        appbook / "frontend" / "index.html",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "OracleHarnessRunStore" in source
    assert "OracleApprovalStore" in source
    assert "OracleProvider" in source
    assert "LiveModelHarness" in source
    assert "provider_request" in source
    assert "provider_response" in source
    assert "/api/executions" in source
    assert 'data-node="meta"' in source
    assert 'data-node="openai-live"' in source
    assert 'data-node="anthropic-live"' in source
    assert 'data-node="deepseek-live"' in source
    assert 'id="node-modal"' in source
    assert not re.search(
        r"sqlite|fixture|test double|deterministic adapter|\bcontract\b",
        source,
        re.IGNORECASE,
    )
    demo_lines = (shared / "metaharness_demo.py").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(demo_lines) < 500


def test_total_recall_ontology_graph_sandbox_context_and_promotion() -> None:
    harness = TotalRecallHarness()
    try:
        graph = harness.ontology.graph()
        assert graph["node_count"] == 17
        assert graph["edge_count"] == 17
        assert graph["all_edges_valid"] is True

        first = harness.run(thread_id="pytest-total-recall-1")
        assert first["status"] == "succeeded"
        assert first["verification"]["verified"] is True
        assert len(first["workflow_view"]["nodes"]) == 10
        assert first["promotion"]["status"] == "candidate"
        envelope = first["state"]["sandbox_trace"][0]
        assert envelope["execution"]["environment_variable_count"] == 0
        assert envelope["execution"]["session_closed"] is True
        assert envelope["output"]["host_recomputation_matched"] is True
        assert first["context_window"]["section_count"] == 7

        second = harness.run(thread_id="pytest-total-recall-2")
        assert second["promotion"]["status"] == "promoted"
        skill = harness.catalog.load_skill("proven-ontology-impact-analysis")
        assert len(skill["sha"]) == 64
        assert "## Steps" in skill["skill_md"]
        assert harness.catalog.recall_workflows(
            "ontology impact analysis", include_promoted=False
        ) == []
    finally:
        harness.close()


def test_total_recall_gpt55_tool_continuation_preserves_reasoning(monkeypatch) -> None:
    import asyncio

    from part_1.advanced.total_recall.appbook.backend.core import agent

    calls: list[dict] = []
    reasoning_item = SimpleNamespace(type="reasoning", id="reasoning-1")
    tool_item = SimpleNamespace(
        type="function_call",
        name="probe_tool",
        arguments='{"value":"ready"}',
        call_id="call-1",
    )

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    output=[reasoning_item, tool_item], output_text=""
                )
            return SimpleNamespace(
                output=[SimpleNamespace(type="message")], output_text="complete"
            )

    monkeypatch.setattr(agent, "client", SimpleNamespace(responses=FakeResponses()))
    monkeypatch.setattr(agent.db, "semantic_search", lambda *_args: [])
    monkeypatch.setattr(agent.memory, "add_turn", lambda *_args: None)
    monkeypatch.setattr(agent.memory, "context_card", lambda *_args: "")
    monkeypatch.setattr(agent.memory, "recall_workflow", lambda *_args: [])
    monkeypatch.setattr(agent.memory, "capture_workflow", lambda *_args: None)
    monkeypatch.setattr(
        agent.registries,
        "TOOLS",
        {"probe_tool": lambda value: {"value": value}},
    )
    monkeypatch.setattr(
        agent.registries,
        "retrieve_tools",
        lambda *_args: [{"NAME": "probe_tool"}],
    )
    monkeypatch.setattr(agent.registries, "build_skill_manifest", lambda *_args: "")
    monkeypatch.setattr(
        agent.registries,
        "get_tool_schema",
        lambda _name: {
            "description": "Return a probe value.",
            "parameters": {"value": "string"},
        },
    )

    async def collect():
        return [event async for event in agent.run_agent("Run the probe Tool.")]

    events = asyncio.run(collect())
    assert calls[0]["model"] == "gpt-5.5"
    assert calls[0]["store"] is False
    assert calls[0]["include"] == ["reasoning.encrypted_content"]
    assert reasoning_item in calls[1]["input"]
    assert tool_item in calls[1]["input"]
    assert any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in calls[1]["input"]
    )
    assert any(event == {"type": "delta", "text": "complete"} for event in events)


def test_total_recall_cross_app_navigation() -> None:
    frontend = (
        ADVANCED / "total_recall/appbook/frontend/index.html"
    ).read_text(encoding="utf-8")
    assert 'aria-label="Harness examples"' in frontend
    for port in range(8010, 8014):
        assert f'href="http://127.0.0.1:{port}"' in frontend
    assert (
        'class="active" href="http://127.0.0.1:8013" aria-current="page"'
        in frontend
    )


def test_all_appbook_surfaces(tmp_path: Path) -> None:
    from part_1.advanced.deep_research.appbook.backend import main as research_api
    from part_1.advanced.metaharness.appbook.backend import main as meta_api
    from part_1.advanced.workflow.appbook.backend import main as workflow_api
    from part_1.advanced.total_recall.appbook.backend import main as total_api

    workflow_api._runtime = WorkflowHarness()
    with TestClient(workflow_api.app) as client:
        frontend = client.get("/")
        assert frontend.status_code == 200
        assert 'id="workflow-svg"' in frontend.text
        assert 'id="skillbox"' in frontend.text
        assert 'id="toolbox"' in frontend.text
        assert 'id="sandbox-trace"' in frontend.text
        assert 'id="promotion"' in frontend.text
        workflow_status = client.get("/api/status").json()
        assert workflow_status["ready"] is True
        assert len(workflow_status["workflow_view"]["nodes"]) == 18
        assert workflow_status["providers"]["toolbox"]["retrieval"] == "semantic vector search"
        assert workflow_status["providers"]["skillbox"]["format"] == "SKILL.md + SHA-256"
        crashed = client.post(
            "/api/runs",
            json={
                "thread_id": "pytest-api-workflow",
                "fail_once_at": "draft_report",
                "requested_by": "pytest-api",
            },
        ).json()
        assert crashed["status"] == "resumable"
        pending = client.post("/api/runs/pytest-api-workflow/resume").json()
        assert pending["status"] == "pending_approval"
        assert client.get("/api/inspector/context").status_code == 200
        assert client.get("/api/inspector/sources").json()["sources"]

    research_api._runtime = DeepResearchHarness(
        config=ResearchConfig.from_env(
            live=False, data_dir=tmp_path / "appbook-research"
        )
    )
    with TestClient(research_api.app) as client:
        assert client.get("/").status_code == 200
        pending = client.post(
            "/api/research/start",
            json={
                "question": "How do governed harnesses improve durable research?",
                "research_id": "pytest-api-research",
                "focus": "evidence reuse",
            },
        )
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending_approval"
        assert pending.json()["approval"]["status"] == "pending"
        completed = client.post(
            "/api/research/approve",
            json={
                "proposal_id": pending.json()["checkpoint"]["proposal_id"],
                "approver_id": "pytest-api-owner",
                "reason": "The exact fixture envelope and verifier were reviewed.",
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"
        assert completed.json()["verified"] is True
        events = client.get(
            f"/api/research/runs/{completed.json()['run_id']}/events"
        )
        assert events.status_code == 200
        assert len(events.json()["events"]) >= 10
        research_context = client.get("/api/inspector/context")
        assert research_context.status_code == 200
        assert research_context.json()["section_count"] >= 4
        research_sources = client.get("/api/inspector/sources")
        assert research_sources.status_code == 200
        assert research_sources.json()["sources"]
        for source in research_sources.json()["sources"]:
            for table in source["tables"]:
                rows = client.get(
                    f"/api/inspector/sources/{source['id']}"
                    f"/tables/{table['name']}/rows",
                    params={"limit": 40, "offset": 0},
                )
                assert rows.status_code == 200, rows.text

    meta_api._runtime = None
    meta_api._startup_error = None
    with TestClient(meta_api.app) as client:
        frontend = client.get("/")
        assert frontend.status_code == 200
        assert 'data-node="meta"' in frontend.text
        assert 'data-node="openai-live"' in frontend.text
        assert 'data-node="anthropic-live"' in frontend.text
        assert 'data-node="deepseek-live"' in frontend.text
        assert 'id="node-modal"' in frontend.text
        meta_status = client.get("/api/status")
        assert meta_status.status_code == 200
        assert meta_status.json()["ready"] is False
        assert "Oracle" in meta_status.json()["remediation"]

    total_api._runtime = TotalRecallHarness()
    with TestClient(total_api.app) as client:
        frontend = client.get("/")
        assert frontend.status_code == 200
        assert 'id="app"' in frontend.text
        assert 'id="advanced-inspector"' in frontend.text
        app_javascript = client.get("/app.js")
        assert app_javascript.status_code == 200
        assert 'id: "ontology"' in app_javascript.text
        assert "Ontology & GraphRAG" in app_javascript.text
        assert "Mission Control" in app_javascript.text
        total_status = client.get("/api/status").json()
        assert total_status["ready"] is True
        assert len(total_status["workflow_view"]["nodes"]) == 10
        ontology_graph = client.get("/api/ontology/graph").json()
        assert ontology_graph["node_count"] == 17
        assert ontology_graph["all_edges_valid"] is True
        result = client.post(
            "/api/ontology/query",
            json={"question": total_status["default_question"], "thread_id": "pytest-total-api"},
        )
        assert result.status_code == 200
        assert result.json()["verification"]["verified"] is True
        assert result.json()["state"]["sandbox_trace"][0]["execution"]["session_closed"] is True
        assert client.get("/api/inspector/context").json()["section_count"] == 7
        assert client.get("/api/inspector/sources").json()["sources"]


def test_research_inspector_survives_provider_setup_failure(monkeypatch) -> None:
    from part_1.advanced.deep_research.appbook.backend import main as research_api

    research_api._runtime = None
    research_api._startup_error = "Missing required runtime values: ANTHROPIC_API_KEY"

    def unavailable_runtime():
        raise RuntimeError(research_api._startup_error)

    monkeypatch.setattr(research_api, "runtime", unavailable_runtime)
    with TestClient(research_api.app) as client:
        context = client.get("/api/inspector/context")
        assert context.status_code == 200
        assert context.json()["phase"] == "provider_setup_blocked"
        sources = client.get("/api/inspector/sources")
        assert sources.status_code == 200
        artifacts = next(
            source for source in sources.json()["sources"] if source["id"] == "artifacts"
        )
        workers = next(
            table for table in artifacts["tables"] if table["name"] == "WORKERS"
        )
        rows = client.get(
            f"/api/inspector/sources/artifacts/tables/{workers['name']}/rows"
        )
        assert rows.status_code == 200
        assert rows.json()["rows"] == []
