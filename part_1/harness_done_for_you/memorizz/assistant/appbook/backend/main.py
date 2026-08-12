"""ERPA on MemoRizz appbook — FastAPI application.

Warms the harness in the background on startup (so the frontend serves immediately),
mounts one router group per harness layer, and serves the dependency-free SPA from the
same origin.

    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import FRONTEND_DIR
from backend.core import store
from backend.routers import memory, overview, the_brief, the_memagent, the_restart, the_store, tools, workshop


def _warm() -> None:
    try:
        store.initialize()          # idempotent: creates only what is missing, never resets
        from backend.core.observability import observability_status
        observability_status()      # persist the stable UI-visible agent when Oracle is configured
    except Exception:
        pass                        # status() records the error; the badge shows it


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title="ERPA on MemoRizz — Appbook", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (workshop.router, memory.router, overview.router, the_brief.router, the_memagent.router,
          the_restart.router, the_store.router, tools.router):
    app.include_router(r)

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
