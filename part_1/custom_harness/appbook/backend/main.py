"""ERPA — Custom Harness appbook — FastAPI application.

Warms the harness in the background on startup (so the frontend serves immediately),
mounts one router group per harness layer, and serves the dependency-free SPA from the
same origin.

    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import threading
from time import perf_counter
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import FRONTEND_DIR, settings
from backend.core import store
from backend.core.scheduler import scheduler
from backend.core.activity import activity, operations_for
from backend.routers import cache, data_explorer, foundation, memory_layer, mission_control, retrieval, semantic_layer, skills, the_loop, tools_and_mcp


def _warm() -> None:
    try:
        if settings.live:
            from backend.core.agent import get_graph
            from backend.core.oracle_live import get_oracle_stack

            get_oracle_stack()      # OAMP, OracleSemanticCache and OracleSaver
            get_graph()             # compile StateGraph with that OracleSaver
        else:
            store.initialize()      # additive local mirror; never resets user state
        scheduler.start()
    except Exception:
        pass                        # status() records the error; the badge shows it


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm, daemon=True).start()
    yield
    scheduler.stop()
    if settings.live:
        from backend.core.oracle_live import close_oracle_stack

        close_oracle_stack()


app = FastAPI(title="ERPA — Custom Harness — Appbook", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def database_activity(request, call_next):
    path = request.url.path
    if path == "/api/data_explorer/activity":
        return await call_next(request)
    operations = operations_for(request.method, path)
    transaction_id = activity.transaction_id()
    started = perf_counter()
    for item in operations:
        await activity.publish(transaction_id=transaction_id, status="active", route=path, **item)
    try:
        response = await call_next(request)
        status = "committed" if response.status_code < 400 else "rolled_back"
        return response
    except Exception:
        status = "rolled_back"
        raise
    finally:
        detail = f"{(perf_counter() - started) * 1000:.1f} ms"
        for item in operations:
            await activity.publish(transaction_id=transaction_id, status=status, route=path, detail=detail, **item)

for r in (cache.router, data_explorer.router, foundation.router, memory_layer.router, mission_control.router, retrieval.router, semantic_layer.router, skills.router, the_loop.router, tools_and_mcp.router,):
    app.include_router(r)

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
