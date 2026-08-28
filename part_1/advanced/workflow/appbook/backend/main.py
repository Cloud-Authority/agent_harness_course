"""FastAPI surface for the durable workflow appbook."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from part_1.advanced.shared.config import settings as default_settings
from part_1.advanced.shared.workflow import WorkflowHarness
from part_1.advanced.shared.inspector import (
    JsonDataSource,
    OracleDataSource,
    build_inspector_router,
)
from part_1.advanced.shared.security import public_error


APPBOOK_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APPBOOK_DIR / "frontend"
IMAGES_DIR = APPBOOK_DIR.parent / "images"
SHARED_FRONTEND = APPBOOK_DIR.parents[1] / "shared" / "frontend"
APPBOOK_SETTINGS = replace(default_settings, backend="oracle")
NOTEBOOK_ALIGNMENT = {
    "notebook": "advanced_durable_workflow.ipynb",
    "persistence_profile": "oracle-only",
    "teaching_graph_nodes": 17,
    "operational_view_nodes": 18,
    "diagram": "/images/Supplier_Renewal_Workflow_OReilly.png",
    "relationship": (
        "The AppBook preserves the Northstar outcome and policy, but its live "
        "operational topology is an extension rather than a node-for-node copy."
    ),
    "trajectories": [
        {
            "supplier": "Northstar Textiles",
            "route": "full review",
            "terminal_authority": "named human approval",
        },
        {
            "supplier": "Bluebird Components",
            "route": "quick review",
            "terminal_authority": "policy approval",
        },
        {
            "supplier": "Contoso Fibres",
            "route": "missing evidence",
            "terminal_authority": "request documents and stop",
        },
    ],
    "operational_extensions": [
        "Oracle Agent Memory context recall",
        "model planning",
        "operation-ledger crash recovery",
        "workflow capture and Skill promotion",
    ],
}

_runtime: WorkflowHarness | None = None
_startup_error: str | None = None
_lock = threading.RLock()


def runtime() -> WorkflowHarness:
    global _runtime, _startup_error
    with _lock:
        if _runtime is None:
            try:
                _runtime = WorkflowHarness(course_settings=APPBOOK_SETTINGS)
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=warm, daemon=True).start()
    yield
    if _runtime is not None:
        _runtime.close()


app = FastAPI(
    title="Supplier Compliance Agent Harness",
    version="1.0.0",
    lifespan=lifespan,
)
class StartRequest(BaseModel):
    thread_id: str | None = None
    fail_once_at: str = Field(default="draft_report", pattern="^(draft_report|none)$")
    requested_by: str = "compliance-operator"


class DecisionRequest(BaseModel):
    approved: bool
    decided_by: str = Field(min_length=2, max_length=200)
    comment: str = Field(default="", max_length=1000)


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": public_error(exc)},
    )


@app.get("/api/status")
async def status():
    try:
        harness = await asyncio.to_thread(runtime)
        current = await asyncio.to_thread(harness.status)
        return {**current, "notebook_alignment": NOTEBOOK_ALIGNMENT}
    except Exception:
        return {
            "ready": False,
            "section": "workflow",
            "error": _startup_error,
            "notebook_alignment": NOTEBOOK_ALIGNMENT,
            "remediation": (
                "Start Oracle AI Database, verify ORA_DSN/ORA_AGENT_USER/"
                "ORA_AGENT_PWD, then reload. This AppBook has no in-memory "
                "persistence profile."
            ),
        }


@app.post("/api/runs")
async def start_run(payload: StartRequest):
    fail_at = "" if payload.fail_once_at == "none" else payload.fail_once_at
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(
        harness.start,
        thread_id=payload.thread_id,
        fail_once_at=fail_at,
        requested_by=payload.requested_by,
    )


@app.post("/api/runs/{thread_id}/resume")
async def resume_run(thread_id: str):
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(harness.resume_after_failure, thread_id)


@app.post("/api/runs/{thread_id}/decision")
async def decide_run(thread_id: str, payload: DecisionRequest):
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(
        harness.decide,
        thread_id,
        approved=payload.approved,
        decided_by=payload.decided_by,
        comment=payload.comment,
    )


@app.get("/api/runs/{thread_id}")
async def inspect_run(thread_id: str):
    harness = await asyncio.to_thread(runtime)
    result = await asyncio.to_thread(harness.inspect, thread_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Unknown workflow thread")
    return result


def inspector_sources(harness: WorkflowHarness):
    if harness.resources.pool is not None:
        return [
            OracleDataSource(
                "oracle",
                "Oracle harness schema",
                harness.resources.pool,
                table_prefixes=("ADV_",),
            )
        ]
    return [
        JsonDataSource(
            "runtime",
            "In-memory harness stores",
            lambda: {
                "TOOLS": list(harness.catalog._tools.values()),
                "SKILLS": list(harness.catalog._skills.values()),
                "WORKFLOWS": list(harness.catalog._workflows.values()),
                "LATEST_EVENTS": (
                    harness.agent_memory.events(harness._latest_thread_id)
                    if harness._latest_thread_id
                    else []
                ),
            },
        )
    ]


app.include_router(
    build_inspector_router(runtime_factory=runtime, source_factory=inspector_sources)
)
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="workflow-images")
app.mount("/shared", StaticFiles(directory=str(SHARED_FRONTEND)), name="shared")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
