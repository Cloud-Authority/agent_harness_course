"""FastAPI delivery surface for live MemoRizz deep research."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from part_1.advanced.deep_research.appbook.backend.runtime import LiveDeepResearchRuntime
from part_1.advanced.shared.inspector import (
    JsonDataSource,
    OracleDataSource,
    SQLiteDataSource,
    build_inspector_router,
    context_window as build_context_window,
)
from part_1.advanced.shared.security import public_error


APPBOOK_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APPBOOK_DIR / "frontend"
SHARED_FRONTEND = APPBOOK_DIR.parents[1] / "shared" / "frontend"

_runtime: Any | None = None
_startup_error: str | None = None
_lock = threading.RLock()


def runtime() -> Any:
    global _runtime, _startup_error
    with _lock:
        if _runtime is None:
            try:
                _runtime = LiveDeepResearchRuntime()
                _startup_error = None
            except Exception as exc:
                _startup_error = public_error(exc)
                raise
        return _runtime


def warm() -> None:
    try:
        runtime()
    except Exception:
        pass


class _ReadOnlyInspectorRuntime:
    """Keep inspection useful when live provider setup is blocked."""

    def __init__(self, error: str | None):
        self.error = error or "The live research runtime is not initialized."
        self._artifacts: dict[str, list[dict[str, Any]]] = {}

    def status(self) -> dict[str, Any]:
        return {"ready": False, "workers": {}, "error": self.error}

    def context_window(self) -> dict[str, Any]:
        return build_context_window(
            [
                {
                    "title": "Runtime readiness",
                    "kind": "control",
                    "source": "appbook host",
                    "content": {
                        "ready": False,
                        "error": self.error,
                        "data_explorer": "runtime snapshot remains available",
                    },
                }
            ],
            provider="none",
            model="none",
            phase="provider_setup_blocked",
            actual_model_call=False,
            note="No model, Tavily, E2B, or Oracle write was attempted.",
        )


def inspector_runtime() -> Any:
    try:
        return runtime()
    except Exception:
        return _ReadOnlyInspectorRuntime(_startup_error)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=warm, daemon=True).start()
    yield
    if _runtime is not None:
        closer = getattr(_runtime, "close", None)
        if callable(closer):
            closer()


app = FastAPI(
    title="Advanced Harness Engineering — Live Deep Research",
    version="2.0.0",
    lifespan=lifespan,
)


class ResearchRequest(BaseModel):
    question: str = Field(min_length=10, max_length=2_000)
    research_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    focus: str = Field(default="", max_length=500)
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)
    approver_id: str = Field(default="appbook-operator", min_length=3, max_length=100)
    confirmed: bool = False

    def steering(self) -> dict[str, Any]:
        return {
            "focus": self.focus,
            "include_domains": self.include_domains,
            "exclude_domains": self.exclude_domains,
        }


class ApprovalRequest(BaseModel):
    proposal_id: str = Field(min_length=10, max_length=200)
    approver_id: str = Field(min_length=3, max_length=100)
    reason: str = Field(
        default="The exact research envelope and provider permissions were reviewed.",
        min_length=10,
        max_length=500,
    )


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=500, content={"detail": public_error(exc)})


@app.get("/api/status")
async def status():
    try:
        harness = await asyncio.to_thread(runtime)
        return await asyncio.to_thread(harness.status)
    except Exception:
        return {
            "ready": False,
            "section": "deep_research",
            "error": _startup_error,
            "remediation": (
                "Verify local Oracle credentials and VECTOR_MEMORY_SIZE, then set "
                "OPENAI_API_KEY, TAVILY_API_KEY, and E2B_API_KEY."
            ),
        }


@app.post("/api/research/live")
async def start_live(payload: ResearchRequest):
    harness = await asyncio.to_thread(runtime)
    starter = getattr(harness, "start_run", None)
    if not callable(starter):
        raise HTTPException(409, "The injected runtime does not support live-flow runs")
    try:
        return await asyncio.to_thread(
            starter,
            payload.question,
            confirmed=payload.confirmed,
            focus=payload.focus,
            include_domains=payload.include_domains,
            exclude_domains=payload.exclude_domains,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, public_error(exc)) from exc


# Compatibility endpoints remain for earlier headless/exact-approval clients.
# The default appbook runtime above is direct MemoRizz and does not use MetaHarness.
@app.post("/api/research/start")
async def start_session(payload: ResearchRequest):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "start_session", None)
    if callable(method):
        return await asyncio.to_thread(
            method,
            payload.question,
            research_id=payload.research_id,
            session_id=payload.session_id,
            steering=payload.steering(),
        )
    return await start_live(payload)


@app.post("/api/research/approve")
async def approve_session(payload: ApprovalRequest):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "approve_session", None)
    if not callable(method):
        raise HTTPException(
            409,
            "This direct-MemAgent appbook uses live-run confirmation, not a MetaHarness proposal.",
        )
    return await asyncio.to_thread(
        method,
        payload.proposal_id,
        approver_id=payload.approver_id,
        reason=payload.reason,
    )


@app.post("/api/research/sessions")
async def run_session(payload: ResearchRequest):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "run_session", None)
    if callable(method):
        return await asyncio.to_thread(
            method,
            payload.question,
            approver_id=payload.approver_id,
            research_id=payload.research_id,
            session_id=payload.session_id,
            steering=payload.steering(),
        )
    return await start_live(payload)


@app.post("/api/research/pair")
async def run_pair(payload: ResearchRequest):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "run_pair", None)
    if not callable(method):
        raise HTTPException(409, "Pair comparison is not part of the direct live appbook")
    return await asyncio.to_thread(
        method,
        payload.question,
        approver_id=payload.approver_id,
        research_id=payload.research_id,
        steering=payload.steering(),
    )


@app.get("/api/research/runs/{run_id}")
async def run_snapshot(run_id: str):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "run_snapshot", None)
    if not callable(method):
        raise HTTPException(404, "Live run snapshots are unavailable for this runtime")
    try:
        return await asyncio.to_thread(method, run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/research/runs/{run_id}/events")
async def events(run_id: str, after: int = Query(0, ge=0)):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "events", None)
    if not callable(method):
        raise HTTPException(404, "Run events are unavailable")
    try:
        try:
            rows = await asyncio.to_thread(method, run_id, after)
        except TypeError:
            rows = await asyncio.to_thread(method, run_id)
        return {"run_id": run_id, "events": rows}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/research/runs/{run_id}/stream")
async def stream_run(run_id: str, after: int = Query(0, ge=0)):
    harness = await asyncio.to_thread(runtime)
    if not callable(getattr(harness, "run_snapshot", None)):
        raise HTTPException(409, "Streaming requires the live direct-MemAgent runtime")

    async def stream():
        cursor = after
        while True:
            try:
                rows = await asyncio.to_thread(harness.events, run_id, cursor)
                snapshot = await asyncio.to_thread(harness.run_snapshot, run_id)
            except KeyError:
                yield "event: error\ndata: {\"detail\":\"unknown run\"}\n\n"
                return
            if rows:
                cursor = max(int(item["seq"]) for item in rows)
                payload = json.dumps(
                    {"events": rows, "snapshot": snapshot},
                    ensure_ascii=False,
                    default=str,
                )
                yield f"id: {cursor}\nevent: update\ndata: {payload}\n\n"
            if snapshot["status"] in {"completed", "review_failed", "failed"}:
                payload = json.dumps({"snapshot": snapshot}, ensure_ascii=False, default=str)
                yield f"event: complete\ndata: {payload}\n\n"
                return
            await asyncio.sleep(0.45)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/research/runs/{run_id}/agents/{role}/context")
async def agent_context(run_id: str, role: str):
    harness = await asyncio.to_thread(runtime)
    method = getattr(harness, "agent_context", None)
    if not callable(method):
        raise HTTPException(404, "Per-agent context inspection is unavailable")
    try:
        return await asyncio.to_thread(method, run_id, role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/research/{research_id}/evidence")
async def evidence(research_id: str):
    harness = await asyncio.to_thread(runtime)
    return {
        "research_id": research_id,
        "evidence": await asyncio.to_thread(harness.evidence_pool, research_id),
    }


@app.get("/api/research/{research_id}/knowledge")
async def knowledge(research_id: str):
    harness = await asyncio.to_thread(runtime)
    return {
        "research_id": research_id,
        "knowledge": await asyncio.to_thread(harness.knowledge, research_id),
    }


def inspector_sources(harness: Any):
    if isinstance(harness, LiveDeepResearchRuntime):
        return [
            OracleDataSource(
                "oracle",
                "MemoRizz private and shared Oracle memory",
                harness.memory_provider.pool,
                table_prefixes=(
                    "MEMAGENT",
                    "CONVERSATION_MEMORY",
                    "TOOL_LOG",
                    "SHARED_",
                    "KNOWLEDGE_BASE",
                    "SUMMARY",
                ),
            ),
            JsonDataSource(
                "runtime",
                "Live run, event, agent, and evidence view",
                harness.inspector_tables,
            ),
        ]

    if hasattr(harness, "config") and hasattr(harness.config, "data_dir"):
        return [
            SQLiteDataSource(
                "runs",
                "Research run and event ledger",
                harness.config.data_dir / "harness-runs.sqlite3",
            ),
            SQLiteDataSource(
                "approvals",
                "Exact approval ledger",
                harness.config.data_dir / "approvals.sqlite3",
            ),
            JsonDataSource(
                "artifacts",
                "Verified research artifacts",
                lambda: {
                    "ARTIFACTS": [
                        item
                        for artifacts in getattr(harness, "_artifacts", {}).values()
                        for item in artifacts
                    ],
                    "WORKERS": [
                        {"name": name, "profile": profile}
                        for name, profile in harness.status().get("workers", {}).items()
                    ],
                },
            ),
        ]

    return [
        JsonDataSource(
            "artifacts",
            "Runtime readiness snapshot",
            lambda: {"ARTIFACTS": [], "WORKERS": []},
        )
    ]


app.include_router(
    build_inspector_router(
        runtime_factory=inspector_runtime,
        source_factory=inspector_sources,
    )
)
app.mount("/shared", StaticFiles(directory=str(SHARED_FRONTEND)), name="shared")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
