"""FastAPI host for the live Oracle-backed MetaHarness appbook."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from part_1.advanced.shared.inspector import (
    JsonDataSource,
    OracleDataSource,
    build_inspector_router,
)
from part_1.advanced.shared.metaharness_demo import MetaHarnessCourse
from part_1.advanced.shared.security import public_error


APPBOOK_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APPBOOK_DIR / "frontend"
SHARED_FRONTEND = APPBOOK_DIR.parents[1] / "shared" / "frontend"

_runtime: MetaHarnessCourse | None = None
_startup_error: str | None = None
_lock = threading.RLock()


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=12_000)
    harness: str = Field(
        default="auto",
        pattern="^(auto|openai-live|anthropic-live|deepseek-live)$",
    )
    thread_id: str = Field(min_length=3, max_length=200)


def runtime() -> MetaHarnessCourse:
    global _runtime, _startup_error
    with _lock:
        if _runtime is None:
            try:
                _runtime = MetaHarnessCourse()
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
    title="Advanced Harness Engineering — Live MetaHarness",
    version="2.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": public_error(exc)})


@app.get("/api/status")
async def status():
    try:
        course = await asyncio.to_thread(runtime)
        return await asyncio.to_thread(course.status)
    except Exception:
        return {
            "ready": False,
            "section": "metaharness",
            "error": _startup_error,
            "remediation": (
                "Configure Oracle AI Database and OPENAI_API_KEY for live memory "
                "embeddings, then restart the appbook."
            ),
        }


@app.post("/api/executions")
async def start_execution(payload: QueryRequest):
    course = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(
        course.start_query,
        payload.query,
        harness=payload.harness,
        thread_id=payload.thread_id,
    )


@app.get("/api/executions/{run_id}")
async def execution(run_id: str):
    course = await asyncio.to_thread(runtime)
    try:
        return await asyncio.to_thread(course.execution, run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/nodes/{node_id}")
async def node_detail(node_id: str, run_id: str | None = None):
    course = await asyncio.to_thread(runtime)
    try:
        return await asyncio.to_thread(course.node_detail, node_id, run_id=run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/runs")
async def runs():
    course = await asyncio.to_thread(runtime)
    return {"runs": await asyncio.to_thread(course.runs)}


def inspector_sources(course: MetaHarnessCourse):
    return [
        OracleDataSource(
            "oracle",
            "Oracle MetaHarness and memory tables",
            course.provider.pool,
            table_prefixes=(
                "MH_",
                "KNOWLEDGE_BASE",
                "CONVERSATION_MEMORY",
                "TOOL_LOG",
            ),
        ),
        JsonDataSource(
            "runtime",
            "Live runtime snapshot",
            lambda: {
                "HARNESSES": course.status()["harnesses"],
                "RUNS": course.runs(),
            },
        ),
    ]


app.include_router(
    build_inspector_router(runtime_factory=runtime, source_factory=inspector_sources)
)
app.mount("/shared", StaticFiles(directory=str(SHARED_FRONTEND)), name="shared")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
