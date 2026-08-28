"""Live Oracle-backed MemoRizz MetaHarness teaching application."""

from __future__ import annotations

import os
import threading
import uuid
from importlib.metadata import version
from pathlib import Path
from typing import Any

from memorizz import OracleConfig, OracleProvider
from memorizz.enums.memory_type import MemoryType
from memorizz.metaharness import (
    HarnessBudget,
    HarnessPermissions,
    HarnessRouter,
    HarnessTask,
    MetaHarness,
)

from .config import (
    AdvancedSettings,
    settings as default_settings,
    usable_runtime_secret,
)
from .inspector import context_window
from .live_model_harness import LiveModelHarness
from .oracle_harness_stores import OracleApprovalStore, OracleHarnessRunStore


COURSE_ROOT = Path(__file__).resolve().parents[3]
METAHARNESS_WORKSPACE = COURSE_ROOT / "part_1" / "advanced" / "metaharness"
MEMORY_ID = "advanced-metaharness-incident-ops"
AGENT_ID = "advanced-metaharness-app"


def build_oracle_provider(
    course_settings: AdvancedSettings = default_settings,
) -> OracleProvider:
    """Create MemoRizz's live Oracle provider from the shared course settings."""

    course_settings.validate_oracle()
    if not usable_runtime_secret(course_settings.openai_api_key):
        raise RuntimeError(
            "OPENAI_API_KEY is required for live memory embeddings in this lesson"
        )
    if course_settings.ora_wallet_location:
        os.environ.setdefault("TNS_ADMIN", course_settings.ora_wallet_location)
    return OracleProvider(
        OracleConfig(
            user=course_settings.ora_user,
            password=course_settings.ora_password,
            dsn=course_settings.ora_dsn,
            schema=course_settings.ora_user,
            index_policy="none",
            in_database_embedding=False,
            embedding_provider="openai",
            embedding_config={
                "api_key": course_settings.openai_api_key,
                "model": course_settings.openai_embed_model,
                "dimensions": course_settings.embedding_dimensions,
            },
            pool_min=course_settings.ora_pool_min,
            pool_max=course_settings.ora_pool_max,
            pool_increment=1,
        )
    )


class MetaHarnessCourse:
    """Small app facade around a live, Oracle-backed MemoRizz MetaHarness."""

    def __init__(
        self,
        *,
        course_settings: AdvancedSettings = default_settings,
        provider: OracleProvider | None = None,
    ) -> None:
        if course_settings.backend != "oracle":
            raise RuntimeError("The MetaHarness lesson requires ADVANCED_BACKEND=oracle")
        self.settings = course_settings
        self.provider = provider or build_oracle_provider(course_settings)
        self.run_store = OracleHarnessRunStore(self.provider.pool)
        self.approval_store = OracleApprovalStore(self.provider.pool)
        self.openai = LiveModelHarness(
            name="openai-live",
            provider="openai",
            model=course_settings.openai_model,
            api_key=course_settings.openai_api_key,
        )
        self.anthropic = LiveModelHarness(
            name="anthropic-live",
            provider="anthropic",
            model=course_settings.anthropic_model,
            api_key=course_settings.anthropic_api_key,
        )
        self.deepseek = LiveModelHarness(
            name="deepseek-live",
            provider="deepseek",
            model=course_settings.deepseek_model,
            api_key=course_settings.deepseek_api_key,
            base_url=course_settings.deepseek_base_url,
        )
        self.adapters = [self.openai, self.anthropic, self.deepseek]
        if not any(adapter.probe().available for adapter in self.adapters):
            raise RuntimeError(
                "Configure OPENAI_API_KEY, ANTHROPIC_API_KEY, or DEEPSEEK_API_KEY "
                "for the live lesson"
            )
        self.service = MetaHarness(
            memory_provider=self.provider,
            adapters=self.adapters,
            run_store=self.run_store,
            approval_store=self.approval_store,
            router=HarnessRouter(
                preference=["deepseek-live", "openai-live", "anthropic-live"],
                allowlist=[adapter.name for adapter in self.adapters],
            ),
            allowed_workspace_roots=[str(METAHARNESS_WORKSPACE)],
            context_max_chars=32_000,
            recover_interrupted=True,
        )
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def task(
        self,
        query: str,
        *,
        harness: str = "auto",
        thread_id: str,
        run_id: str | None = None,
    ) -> HarnessTask:
        normalized = str(query or "").strip()
        if not normalized:
            raise ValueError("query cannot be empty")
        if len(normalized) > 12_000:
            raise ValueError("query cannot exceed 12,000 characters")
        selected = str(harness or "auto").strip().lower()
        if selected not in {"auto", *(adapter.name for adapter in self.adapters)}:
            raise ValueError(
                "harness must be auto, openai-live, anthropic-live, or deepseek-live"
            )
        return HarnessTask(
            task=normalized,
            workspace=str(METAHARNESS_WORKSPACE),
            harness=selected,
            memory_id=MEMORY_ID,
            user_id=self.settings.user_id,
            thread_id=str(thread_id),
            agent_id=AGENT_ID,
            permissions=HarnessPermissions(
                workspace_mode="read_only",
                network="full",
                mcp_access="none",
                require_approval=False,
                allowed_env=[],
            ),
            budget=HarnessBudget(
                max_wall_time_seconds=180,
                max_steps=4,
                max_input_tokens=32_000,
                max_output_tokens=4_000,
                max_retries=1,
            ),
            context={"memory_query": normalized},
            metadata={
                "live_provider_request": True,
                "network_policy": "application-owned provider allowlist",
            },
            run_id=run_id or str(uuid.uuid4()),
        )

    def _remember(self, task: HarnessTask, result: dict[str, Any]) -> str | None:
        if result.get("status") != "succeeded":
            return None
        try:
            for role, content in (
                ("user", task.task),
                ("assistant", str(result.get("final_response") or "")),
            ):
                self.provider.store(
                    data={
                        "memory_id": task.memory_id,
                        "thread_id": task.thread_id,
                        "role": role,
                        "content": content,
                        "agent_id": AGENT_ID,
                        "user_id": task.user_id,
                    },
                    memory_store_type=MemoryType.CONVERSATION_MEMORY,
                    memory_id=task.memory_id,
                )
            return None
        except Exception as exc:
            return f"{type(exc).__name__}: response completed but memory write failed"

    def start_query(
        self, query: str, *, harness: str = "auto", thread_id: str
    ) -> dict[str, Any]:
        task = self.task(query, harness=harness, thread_id=thread_id)
        with self._lock:
            self._jobs[task.run_id] = {
                "run_id": task.run_id,
                "phase": "starting",
                "requested_harness": task.harness,
                "query": task.task,
                "thread_id": task.thread_id,
                "terminal": False,
            }
            worker = threading.Thread(
                target=self._run_background,
                args=(task,),
                name=f"metaharness-app-{task.run_id[:8]}",
                daemon=True,
            )
            self._threads[task.run_id] = worker
            worker.start()
            return dict(self._jobs[task.run_id])

    def _run_background(self, task: HarnessTask) -> None:
        try:
            with self._lock:
                self._jobs[task.run_id]["phase"] = "orchestrating"
            result = self.service.run(task).to_dict()
            with self._lock:
                self._jobs[task.run_id]["phase"] = "writing_memory"
            memory_error = self._remember(task, result)
            with self._lock:
                self._jobs[task.run_id].update(
                    {
                        "phase": "complete",
                        "terminal": True,
                        "result": result,
                        "memory_error": memory_error,
                    }
                )
        except Exception as exc:
            with self._lock:
                self._jobs[task.run_id].update(
                    {
                        "phase": "failed",
                        "terminal": True,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        finally:
            with self._lock:
                self._threads.pop(task.run_id, None)

    def execution(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            job = dict(self._jobs.get(str(run_id)) or {})
        run = self.service.get_run(run_id)
        events = self.service.events(run_id) if run else []
        if not job and not run:
            raise KeyError(f"Unknown run: {run_id}")
        terminal_statuses = {
            "succeeded",
            "failed",
            "canceled",
            "interrupted",
            "budget_exceeded",
            "verification_failed",
        }
        terminal = (
            bool(job.get("terminal"))
            if job
            else bool(run and run["status"] in terminal_statuses)
        )
        return {
            **job,
            "run_id": str(run_id),
            "run": run,
            "events": events,
            "terminal": terminal,
        }

    def status(self) -> dict[str, Any]:
        with self.provider.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT version_full FROM product_component_version "
                    "WHERE product LIKE 'Oracle%Database%' FETCH FIRST 1 ROW ONLY"
                )
                row = cursor.fetchone()
        harnesses = self.service.list_harnesses(probe=True)
        return {
            "ready": True,
            "section": "metaharness",
            "memorizz_version": version("memorizz"),
            "database": "Oracle AI Database",
            "oracle_version": str(row[0]) if row else "unknown",
            "memory_provider": type(self.provider).__name__,
            "embedding_provider": "OpenAI",
            "embedding_model": self.settings.openai_embed_model,
            "embedding_dimensions": self.settings.embedding_dimensions,
            "run_store": type(self.run_store).__name__,
            "approval_store": type(self.approval_store).__name__,
            "harnesses": harnesses,
            "run_count": len(self.service.list_runs(limit=1_000)),
        }

    def runs(self) -> list[dict[str, Any]]:
        return self.service.list_runs(limit=200)

    def _selected_adapter(self, run: dict[str, Any] | None) -> LiveModelHarness | None:
        selected = str((run or {}).get("routing", {}).get("selected") or "")
        return next((item for item in self.adapters if item.name == selected), None)

    def node_detail(self, node_id: str, *, run_id: str | None = None) -> dict[str, Any]:
        run = self.service.get_run(run_id) if run_id else None
        events = self.service.events(run_id) if run else []
        result = dict((run or {}).get("result") or {})
        selected = self._selected_adapter(run)
        definitions = {
            "request": ("User request", "The live query and its tenant/thread scope."),
            "meta": ("MemoRizz MetaHarness", "The outer loop that prepares, routes, runs, and records."),
            "router": ("HarnessRouter", "Selects an available allowlisted harness without model authority."),
            "oracle-context": ("Oracle context", "Tenant-scoped memory retrieved before the provider call."),
            "openai-live": ("OpenAI harness", "A real Responses API adapter."),
            "anthropic-live": ("Anthropic harness", "A real Messages API adapter."),
            "deepseek-live": (
                "DeepSeek harness",
                "A real DeepSeek Chat Completions adapter using the OpenAI-compatible endpoint.",
            ),
            "oracle-evidence": ("Oracle evidence", "Durable run rows, normalized events, and conversation memory."),
            "response": ("Application response", "The selected harness output returned to the caller."),
        }
        if node_id not in definitions:
            raise KeyError(f"Unknown diagram node: {node_id}")
        title, description = definitions[node_id]
        sections: list[dict[str, Any]] = []
        provider = "MemoRizz host"
        model = "none"
        actual_call = False
        if node_id in {"openai-live", "anthropic-live", "deepseek-live"}:
            adapter = next(item for item in self.adapters if item.name == node_id)
            saved_input = adapter.input_for(run_id or "")
            sections = list((saved_input or {}).get("sections") or [])
            if not sections:
                sections = [
                    {
                        "title": "Harness readiness",
                        "kind": "control",
                        "content": adapter.probe().to_dict(),
                    }
                ]
            provider = adapter.provider
            model = adapter.model
            actual_call = saved_input is not None
        elif node_id == "request":
            sections = [
                {
                    "title": "HarnessTask input",
                    "kind": "user",
                    "content": (run or {}).get("task", {}),
                }
            ]
        elif node_id == "router":
            sections = [
                {
                    "title": "Routing decision",
                    "kind": "control",
                    "content": (run or {}).get("routing", {}),
                }
            ]
        elif node_id == "oracle-context":
            saved_input = selected.input_for(run_id or "") if selected else None
            sections = [
                item
                for item in (saved_input or {}).get("sections", [])
                if item.get("kind") == "memory"
            ]
            if not sections:
                sections = [
                    {
                        "title": "Context state",
                        "kind": "memory",
                        "content": result.get("context_pack")
                        or "Context has not been assembled yet.",
                    }
                ]
        elif node_id == "oracle-evidence":
            sections = [
                {"title": "Run row", "kind": "evidence", "content": run or {}},
                {"title": "Normalized events", "kind": "evidence", "content": events},
            ]
        elif node_id == "response":
            sections = [
                {
                    "title": "Final response",
                    "kind": "assistant",
                    "content": result.get("final_response") or "No response yet.",
                }
            ]
        else:
            sections = [
                {"title": "Task", "kind": "user", "content": (run or {}).get("task", {})},
                {"title": "Routing", "kind": "control", "content": (run or {}).get("routing", {})},
                {"title": "Events", "kind": "evidence", "content": events},
            ]
        window = context_window(
            sections,
            provider=provider,
            model=model,
            phase=str((run or {}).get("status") or "ready"),
            actual_model_call=actual_call,
            max_tokens=32_000 if actual_call else None,
            note="This view shows assembled inputs and host evidence, never private reasoning.",
        )
        return {
            "node_id": node_id,
            "title": title,
            "description": description,
            "selected": bool(selected and selected.name == node_id),
            "context_window": window,
        }

    def context_window(self) -> dict[str, Any]:
        latest = self.service.list_runs(limit=1)
        if not latest:
            return context_window(
                [
                    {
                        "title": "Awaiting first live query",
                        "kind": "control",
                        "content": "Submit a query to assemble a model input.",
                    }
                ],
                provider="MemoRizz MetaHarness",
                model="not selected",
                phase="ready",
                actual_model_call=False,
            )
        run_id = latest[0]["run_id"]
        selected = self._selected_adapter(latest[0])
        if selected:
            return self.node_detail(selected.name, run_id=run_id)["context_window"]
        return self.node_detail("meta", run_id=run_id)["context_window"]

    def close(self) -> None:
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=5.0)
        self.service.close()
        self.approval_store.close()
        self.provider.close()

__all__ = [
    "AGENT_ID",
    "LiveModelHarness",
    "MEMORY_ID",
    "METAHARNESS_WORKSPACE",
    "MetaHarnessCourse",
    "build_oracle_provider",
]
