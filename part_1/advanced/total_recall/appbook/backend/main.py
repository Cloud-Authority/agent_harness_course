"""FastAPI surface for the layered Total Recall appbook and ontology explorer."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from part_1.advanced.shared.config import settings as shared_settings
from part_1.advanced.shared.inspector import (
    JsonDataSource,
    OracleDataSource,
    build_inspector_router,
    context_window,
)
from part_1.advanced.shared.security import public_error
from part_1.advanced.shared.total_recall import TotalRecallHarness, TotalRecallState

from .config import FRONTEND_DIR, settings
from .core import db
from .routers import agentloop, automations, layers, memory, skills


APPBOOK_DIR = Path(__file__).resolve().parents[1]
SHARED_FRONTEND = APPBOOK_DIR.parents[1] / "shared" / "frontend"

_runtime: TotalRecallHarness | None = None
_startup_error: str | None = None
_runtime_lock = threading.RLock()
_runtime_settings = replace(
    shared_settings,
    semantic_backend="oracle",
    agent_memory_search_strategy="keyword",
    agent_memory_store_id="tr_ontology",
)


def runtime() -> TotalRecallHarness:
    global _runtime, _startup_error
    with _runtime_lock:
        if _runtime is None:
            try:
                _runtime = TotalRecallHarness(course_settings=_runtime_settings)
                _startup_error = None
            except Exception as exc:
                _startup_error = public_error(exc)
                raise
        return _runtime


def _warm() -> None:
    if not settings.oracle_enabled:
        return
    try:
        db.initialize()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(_warm)
    yield
    if _runtime is not None:
        _runtime.close()


app = FastAPI(
    title="Total Recall — Agent Memory and Harness Engineering",
    version="2.0.0",
    lifespan=lifespan,
)

for router in (layers.router, memory.router, skills.router, agentloop.router, automations.router):
    app.include_router(router)


class QueryRequest(BaseModel):
    question: str = Field(min_length=10, max_length=2000)
    thread_id: str | None = Field(default=None, max_length=200)


class RefreshRequest(BaseModel):
    trigger: str = Field(default="manual", pattern="^(manual|scheduler)$")


_WORKFLOW_IDS = (
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
)


def _preview_node(_state: TotalRecallState) -> dict:
    return {}


@lru_cache(maxsize=1)
def _workflow_preview() -> dict:
    """Compile the visible topology without opening provider or memory clients."""
    builder = StateGraph(TotalRecallState)
    for name in _WORKFLOW_IDS[1:-1]:
        builder.add_node(name, _preview_node)
    builder.add_edge(START, _WORKFLOW_IDS[1])
    for left, right in zip(_WORKFLOW_IDS[1:-2], _WORKFLOW_IDS[2:-1]):
        builder.add_edge(left, right)
    builder.add_edge(_WORKFLOW_IDS[-2], END)
    graph = builder.compile()
    return {
        "view": {
            "nodes": [
                {
                    "id": name,
                    "label": name.replace("_", " ").title(),
                    "status": "pending",
                    "kind": "boundary" if name in {"start", "end"} else "harness_node",
                }
                for name in _WORKFLOW_IDS
            ],
            "edges": [
                {"source": left, "target": right}
                for left, right in zip(_WORKFLOW_IDS, _WORKFLOW_IDS[1:])
            ],
            "run_status": "awaiting_run",
        },
        "mermaid": graph.get_graph().draw_mermaid(),
    }


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": public_error(exc)})


@app.get("/api/status")
async def status():
    try:
        harness = await asyncio.to_thread(runtime)
        return await asyncio.to_thread(harness.status)
    except Exception:
        return {
            "ready": False,
            "section": "total_recall",
            "error": _startup_error,
            "remediation": "Verify Oracle, embedding-model, and OpenAI configuration.",
        }


@app.get("/api/workflow")
async def workflow():
    with _runtime_lock:
        harness = _runtime
    if harness is None:
        return _workflow_preview()
    return {
        "view": harness.workflow_view(),
        "mermaid": await asyncio.to_thread(harness.graph_mermaid),
    }


@app.get("/api/ontology/schema")
async def ontology_schema():
    harness = await asyncio.to_thread(runtime)
    terms = await asyncio.to_thread(harness.ontology.terms)
    return {
        "classes": [item for item in terms if item["term_kind"] == "class"],
        "properties": [item for item in terms if item["term_kind"] == "property"],
        "native_rdf": await asyncio.to_thread(harness.ontology.native_rdf_status),
    }


@app.get("/api/ontology/terms/{term_id}")
async def ontology_term(term_id: str):
    harness = await asyncio.to_thread(runtime)
    terms = await asyncio.to_thread(harness.ontology.terms)
    match = next((item for item in terms if item["term_id"] == term_id), None)
    if match is None:
        raise HTTPException(404, "Unknown ontology term")
    return match


@app.get("/api/ontology/graph")
async def ontology_graph():
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(harness.ontology.graph)


@app.post("/api/ontology/query")
async def ontology_query(payload: QueryRequest):
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(
        harness.run, payload.question, thread_id=payload.thread_id
    )


@app.post("/api/ontology/refresh")
async def ontology_refresh(payload: RefreshRequest):
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(harness.ontology.refresh, trigger=payload.trigger)


@app.get("/api/ontology/scheduler")
async def ontology_scheduler():
    harness = await asyncio.to_thread(runtime)
    return await asyncio.to_thread(harness.ontology.scheduler_status)


@app.get("/api/ontology/history")
async def ontology_history():
    harness = await asyncio.to_thread(runtime)
    return {
        "refreshes": await asyncio.to_thread(harness.ontology.refresh_history),
        "queries": await asyncio.to_thread(harness.ontology.query_history),
    }


class _InspectorRuntime:
    def status(self) -> dict:
        return {
            "section": "total_recall",
            "appbook": db.status(),
            "provider": "OpenAI Responses API",
            "model": settings.model,
        }

    def context_window(self) -> dict:
        return context_window(
            [
                {
                    "title": "Model policy",
                    "kind": "control",
                    "content": {
                        "provider": "OpenAI Responses API",
                        "model": settings.model,
                        "store": False,
                    },
                },
                {
                    "title": "Oracle retrieval substrate",
                    "kind": "retrieval",
                    "content": {
                        "embedding_model": settings.embed_model,
                        "dimensions": settings.vector_dim,
                        "status": db.status(),
                    },
                },
            ],
            provider="OpenAI Responses API",
            model=settings.model,
            phase="awaiting_agent_run",
            actual_model_call=False,
        )


_inspector_runtime = _InspectorRuntime()


def inspector_runtime():
    with _runtime_lock:
        return _runtime or _inspector_runtime


def inspector_sources(active_runtime):
    if isinstance(active_runtime, TotalRecallHarness):
        if active_runtime.resources.pool is not None:
            return [
                OracleDataSource(
                    "oracle",
                    "Oracle harness, memory, registry, and ontology schema",
                    active_runtime.resources.pool,
                )
            ]
        return [
            JsonDataSource(
                "runtime",
                "Ontology, Skillbox, and Toolbox snapshot",
                active_runtime.explorer_snapshot,
            )
        ]
    if settings.oracle_enabled:
        return [
            OracleDataSource(
                "oracle",
                "Oracle harness, memory, registry, and ontology schema",
                db.pool(),
            )
        ]
    return [
        JsonDataSource(
            "runtime",
            "Ontology, Skillbox, and Toolbox snapshot",
            lambda: {"appbook_status": [db.status()]},
        )
    ]


app.include_router(
    build_inspector_router(
        runtime_factory=inspector_runtime,
        source_factory=inspector_sources,
    )
)
app.mount("/images", StaticFiles(directory=str(APPBOOK_DIR / "images")), name="images")
app.mount("/shared", StaticFiles(directory=str(SHARED_FRONTEND)), name="shared")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8013)
