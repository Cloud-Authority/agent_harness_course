"""The survey-paper appbook: FastAPI in front of the deep-research harness."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent
ADVANCED = BACKEND.parents[2]
sys.path.insert(0, str(ADVANCED))
from shared.appbook import Bus, add_paths, explorer_rows, explorer_tables, load_env  # noqa: E402

add_paths(BACKEND)
load_env()
os.environ.setdefault("SURVEY_OUTPUT_DIR", str(BACKEND.parents[1] / "output"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402

from shared import oracle  # noqa: E402

app = FastAPI(title="Survey paper appbook")
bus = Bus()
STATE: dict[str, Any] = {"ready": False, "error": None, "runs": {}}
PREFIXES = ("SURVEY_",)


def _install_bus() -> None:
    from harness import evidence, graph, reading, tables, writing
    original = tables.ledger
    if getattr(original, "__wrapped__", None):
        return
    def ledger(paper_id: str, node: str, kind: str, detail: Any) -> None:
        original(paper_id, node, kind, detail)
        bus.publish("ledger", paper_id=paper_id, node=node, kind=kind, detail=detail)
    ledger.__wrapped__ = original  # type: ignore[attr-defined]
    tables.ledger = ledger
    graph.ledger = ledger


def _warm() -> None:
    try:
        oracle.ensure_schema()
        oracle.ensure_embedding_model()
        from harness import graph
        graph.durable_graph()
        _install_bus()
        STATE["ready"] = True
        bus.publish("status", ready=True)
    except Exception as error:  # noqa: BLE001
        STATE["error"] = f"{type(error).__name__}: {str(error)[:300]}"
        bus.publish("status", ready=False, error=STATE["error"])


@app.on_event("startup")
async def startup() -> None:
    bus.loop = asyncio.get_running_loop()
    threading.Thread(target=_warm, name="warm", daemon=True).start()


def ready() -> None:
    if not STATE["ready"]:
        raise HTTPException(503, STATE["error"] or "The harness is still starting.")


def _run(paper_id: str, work) -> None:
    if STATE["runs"].get(paper_id, {}).get("busy"):
        raise HTTPException(409, "This paper is still working on the previous step.")
    STATE["runs"][paper_id] = {"busy": True, "error": None, "since": time.time()}

    def body():
        from harness import graph
        try:
            work()
            STATE["runs"][paper_id] = {"busy": False, "error": None}
            bus.publish("paper", paper_id=paper_id, outcome=_brief(graph.outcome(paper_id)))
        except Exception as error:  # noqa: BLE001
            STATE["runs"][paper_id] = {"busy": False, "error": f"{type(error).__name__}: {str(error)[:300]}"}
            bus.publish("paper", paper_id=paper_id, error=STATE["runs"][paper_id]["error"])
    threading.Thread(target=body, name=f"paper-{paper_id}", daemon=True).start()


def _brief(out: dict) -> dict:
    return {k: v for k, v in out.items() if k not in ("log", "taxonomy")}


class PaperReq(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    audience: str = Field(default="researchers and engineers building agent systems", max_length=200)


class DecisionReq(BaseModel):
    decision: str = Field(pattern=r"^(approve|revise|reject)$")
    note: str = ""


class QueryReq(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=6, ge=1, le=20)


@app.get("/api/status")
def status() -> dict:
    from harness.config import CFG
    from harness.llm import USAGE
    info = {"ready": STATE["ready"], "error": STATE["error"], "model": CFG.model,
            "limits": {"sections": CFG.sections, "sources_per_section": CFG.sources_per_section,
                       "min_words": CFG.min_words_per_section, "min_citations": CFG.min_citations_per_section,
                       "max_rounds": CFG.max_rounds},
            "keys": {"anthropic": bool(os.getenv("ANTHROPIC_API_KEY")), "tavily": bool(os.getenv("TAVILY_API_KEY"))},
            "database": {"dsn": oracle.ORA.dsn, "user": oracle.ORA.user, "reachable": oracle.reachable()},
            "usage": dict(USAGE), "runs": dict(STATE["runs"])}
    if STATE["ready"]:
        info["database"]["version"] = STATE.setdefault("version", oracle.version())   # the explorer lists tables when opened
    return info


@app.get("/api/events")
async def events():
    return EventSourceResponse(bus.stream())


@app.get("/api/graph")
def graph_shape() -> dict:
    ready()
    from harness import graph as g
    drawn = g.build_graph().get_graph()
    notes = {"scope": "Research questions, inclusion criteria, an outline with queries per section",
             "outline_review": "interrupt(): nothing is read before a person approves the plan",
             "rescope": "The reader's note goes back into scope", "gather": "One task per section, made with Send: search, read pages, store with embeddings",
             "read": "Unread sources become typed notes, four per call, on a small pool",
             "organise": "Framework, comparison table and open questions from the notes",
             "write": "One task per section: evidence pack, then a typed draft citing only its pack",
             "review": "Referee pass by the model, plus the harness's own rules", "assemble": "Numbered citations, references, abstract, how it was made",
             "publication_review": "interrupt(): the paper waits for a person", "publish": "Markdown and HTML files", "close": "Declined"}
    return {"nodes": [{"id": n, "note": notes.get(n, "")} for n in drawn.nodes if not n.startswith("__")],
            "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional}
                      for e in drawn.edges if not e.source.startswith("__") and not e.target.startswith("__")]}


@app.get("/api/papers")
def papers() -> dict:
    ready()
    found = oracle.rows("SELECT paper_id, subject, title, status, created_at, updated_at FROM survey_papers "
                        "ORDER BY created_at DESC FETCH FIRST 30 ROWS ONLY")
    return {"papers": [{**r, "busy": STATE["runs"].get(r["paper_id"], {}).get("busy", False)} for r in found]}


@app.post("/api/papers")
def start(req: PaperReq) -> dict:
    ready()
    from harness import graph, tables
    paper_id = tables.new_id("PAPER")
    oracle.execute("INSERT INTO survey_papers (paper_id, subject, brief, status) VALUES (:1, :2, :3, 'STARTED')",
                   [paper_id, req.subject, json.dumps({"audience": req.audience})])
    _run(paper_id, lambda: graph.start_paper(req.subject, req.audience, paper_id=paper_id))
    return {"paper_id": paper_id, "status": "running"}


@app.get("/api/papers/{paper_id}")
def paper(paper_id: str) -> dict:
    ready()
    from harness import graph, tables
    out = graph.outcome(paper_id)
    run = STATE["runs"].get(paper_id, {})
    return {**out, "busy": run.get("busy", False), "error": run.get("error"), "ledger": tables.paper_ledger(paper_id),
            "sources_by_section": oracle.rows("SELECT section_key, COUNT(*) AS n FROM survey_sources WHERE paper_id = :p "
                                              "GROUP BY section_key ORDER BY 1", {"p": paper_id}),
            "reviews": oracle.rows("SELECT round, verdict, findings FROM survey_reviews WHERE paper_id = :p ORDER BY at",
                                   {"p": paper_id})}


@app.get("/api/papers/{paper_id}/sources")
def sources(paper_id: str) -> dict:
    ready()
    from harness.evidence import sources_for
    return {"sources": sources_for(paper_id)}


@app.post("/api/papers/{paper_id}/similar")
def similar(paper_id: str, req: QueryReq) -> dict:
    ready()
    from harness.evidence import similar_sources
    return {"query": req.query, "sources": similar_sources(paper_id, req.query, req.limit)}


@app.get("/api/papers/{paper_id}/notes")
def notes(paper_id: str, section: str | None = None) -> dict:
    ready()
    from harness.reading import notes_for
    return {"notes": notes_for(paper_id, section)}


@app.get("/api/papers/{paper_id}/sections")
def sections(paper_id: str) -> dict:
    ready()
    from harness.writing import drafts
    return {"sections": drafts(paper_id)}


@app.get("/api/papers/{paper_id}/paper.md", response_class=PlainTextResponse)
def paper_markdown(paper_id: str) -> str:
    ready()
    found = oracle.rows("SELECT markdown FROM survey_papers WHERE paper_id = :p", {"p": paper_id})
    if not found or not found[0]["markdown"]:
        raise HTTPException(404, "The paper is not assembled yet.")
    return found[0]["markdown"]


@app.get("/api/papers/{paper_id}/paper.html", response_class=HTMLResponse)
def paper_html(paper_id: str) -> str:
    ready()
    found = oracle.rows("SELECT html FROM survey_papers WHERE paper_id = :p", {"p": paper_id})
    if not found or not found[0]["html"]:
        raise HTTPException(404, "The paper is not assembled yet.")
    return found[0]["html"]


@app.post("/api/papers/{paper_id}/decide")
def decide(paper_id: str, req: DecisionReq) -> dict:
    ready()
    from harness import graph
    if not graph.outcome(paper_id)["waiting_for_person"]:
        raise HTTPException(409, "This paper is not waiting for a decision.")
    _run(paper_id, lambda: graph.resume_paper(paper_id, req.decision, req.note))
    return {"paper_id": paper_id, "status": "running"}


@app.post("/api/papers/{paper_id}/continue")
def resume(paper_id: str) -> dict:
    ready()
    from harness import graph
    _run(paper_id, lambda: graph.continue_paper(paper_id))
    return {"paper_id": paper_id, "status": "running"}


@app.get("/api/explorer/tables")
def tables_listed() -> dict:
    ready()
    return {"tables": explorer_tables(PREFIXES)}


@app.get("/api/explorer/tables/{name}/rows")
def table_rows(name: str, limit: int = 50, offset: int = 0, search: str = "") -> dict:
    ready()
    try:
        return explorer_rows(name, PREFIXES, limit, offset, search)
    except KeyError:
        raise HTTPException(404, "That table is not part of the harness")


@app.post("/api/reset")
def reset() -> dict:
    ready()
    from harness import tables
    tables.reset_survey_tables()
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        oracle.execute(f"DELETE FROM {table} WHERE thread_id LIKE 'PAPER-%'")
    STATE["runs"] = {}
    return {"reset": True}


@app.exception_handler(Exception)
async def unexpected(request, exc: Exception):
    return JSONResponse({"detail": f"{type(exc).__name__}: {str(exc)[:300]}"}, status_code=500)


class Frontend(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/shared", Frontend(directory=str(ADVANCED / "shared" / "frontend")), name="shared")
app.mount("/", Frontend(directory=str(BACKEND.parent / "frontend"), html=True), name="frontend")
