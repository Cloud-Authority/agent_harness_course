"""The research graph: plan, ask, gather in parallel, read, organise, write in parallel, review, assemble, ask."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from langgraph_oracledb.checkpoint.oracle import OracleSaver

from shared.oracle import execute, pool, rows

from .config import CFG
from .evidence import gather_for_section, sources_for
from .llm import USAGE
from .reading import read_sources
from .tables import create_survey_tables, ledger, new_id
from .writing import (assemble_paper, build_taxonomy, check_drafts, drafts, review_paper, scope_paper,
                      to_html, write_section)

OUTPUT_DIR = Path(os.getenv("SURVEY_OUTPUT_DIR", "output"))     # where published papers are written
EVIDENCE_KINDS = {"background", "framework", "thematic", "evaluation", "outlook"}


class PaperState(TypedDict, total=False):
    paper_id: str
    subject: str
    audience: str
    title: str
    scope: dict
    outline: list[dict]
    note: str
    rescopes: int
    sources: Annotated[list, add]
    written: Annotated[list, add]
    taxonomy: dict
    review: dict
    problems: list[dict]
    round: int
    paper: dict
    decision: dict
    status: str
    log: Annotated[list, add]


def note_step(state: PaperState, node: str, kind: str, detail: Any) -> dict:
    ledger(state["paper_id"], node, kind, detail)
    return {"log": [{"node": node, "kind": kind, "detail": detail}]}


def maybe_crash(node: str) -> None:
    if CFG.crash_after == node:
        sys.stdout.flush()
        os._exit(3)


def set_status(paper_id: str, status: str, **fields) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    execute(f"UPDATE survey_papers SET status = :status, updated_at = SYSTIMESTAMP{', ' + sets if sets else ''} "
            f"WHERE paper_id = :paper_id", {"status": status, "paper_id": paper_id, **fields})


# ── nodes ────────────────────────────────────────────────────────────────────

def scope(state: PaperState) -> dict:
    request = state["subject"] + (f"\n\nThe reader of the previous outline asked: {state['note']}" if state.get("note") else "")
    found = scope_paper(request, state["audience"])
    outline = [{**s, "position": n + 1} for n, s in enumerate(found["sections"])]
    changed = execute("UPDATE survey_papers SET outline = :o, title = :t, status = 'OUTLINED', updated_at = SYSTIMESTAMP "
                      "WHERE paper_id = :id", {"o": json.dumps(outline), "t": found["title"][:500], "id": state["paper_id"]})
    if not changed:
        execute("INSERT INTO survey_papers (paper_id, subject, brief, status, title, outline) "
                "VALUES (:id, :sub, :b, 'OUTLINED', :t, :o)",
                {"id": state["paper_id"], "sub": state["subject"][:500], "b": json.dumps({"audience": state["audience"]}),
                 "t": found["title"][:500], "o": json.dumps(outline)})
    return {"scope": found, "title": found["title"], "outline": outline, "status": "awaiting_outline",
            **note_step(state, "scope", "outline", [(s["key"], s["title"]) for s in outline])}


def outline_review(state: PaperState) -> dict:
    """Nothing is read, and nothing is paid for, before a person accepts the plan."""
    decision = interrupt({"paper_id": state["paper_id"], "title": state["title"], "scope": state["scope"],
                          "outline": state["outline"], "options": ["approve", "revise", "reject"]})
    return {"decision": decision, "note": decision.get("note", ""),
            **note_step(state, "outline_review", "decision", decision)}


def after_outline_review(state: PaperState):
    verdict = state["decision"].get("decision")
    if verdict == "revise" and state.get("rescopes", 0) < 2:
        return "rescope"
    if verdict != "approve":
        return "close"
    return [Send("gather", {"paper_id": state["paper_id"], "subject": state["subject"], "section": s,
                            "queries": s["queries"], "round": 1})
            for s in state["outline"] if s["kind"] in EVIDENCE_KINDS]


def rescope(state: PaperState) -> dict:
    return {"rescopes": state.get("rescopes", 0) + 1, **note_step(state, "rescope", "note", state.get("note", ""))}


def gather(task: dict) -> dict:
    """One section's searches. Runs beside the other sections."""
    kept = gather_for_section(task["paper_id"], task["section"], task["queries"], task["round"])
    ledger(task["paper_id"], "gather", "sources", {"section": task["section"]["key"], "kept": len(kept)})
    return {"sources": kept, "log": [{"node": "gather", "kind": "sources",
                                      "detail": {"section": task["section"]["key"], "kept": len(kept)}}]}


def read(state: PaperState) -> dict:
    """Every stored page without notes is read, a few sources per model call, in parallel."""
    unread = [r["source_id"] for r in rows(
        "SELECT s.source_id FROM survey_sources s WHERE s.paper_id = :p AND NOT EXISTS "
        "(SELECT 1 FROM survey_notes n WHERE n.source_id = s.source_id) ORDER BY s.fetched_at", {"p": state["paper_id"]})]
    batches = [unread[i:i + CFG.read_batch] for i in range(0, len(unread), CFG.read_batch)]
    with ThreadPoolExecutor(max_workers=4) as workers:
        done = sum(len(n) for n in workers.map(lambda b: read_sources(state["paper_id"], state["subject"], b), batches))
    set_status(state["paper_id"], "READ")
    result = {"status": "read", **note_step(state, "read", "notes", {"sources": len(unread), "notes": done})}
    maybe_crash("read")
    return result


def organise(state: PaperState) -> dict:
    taxonomy = build_taxonomy(state["paper_id"], state["subject"])
    return {"taxonomy": taxonomy, "round": state.get("round", 0) + 1,
            **note_step(state, "organise", "taxonomy", {"framework": taxonomy["framework_name"],
                                                         "categories": [c["name"] for c in taxonomy["categories"]],
                                                         "compared": len(taxonomy["comparison"]["rows"])})}


def fan_out_write(state: PaperState):
    feedback = {s["key"]: s for s in state.get("review", {}).get("sections", [])}
    to_write = state["outline"] if state.get("round", 1) == 1 else [
        s for s in state["outline"] if feedback.get(s["key"], {}).get("needs_more_evidence")
        or any(p["key"] == s["key"] for p in state.get("problems", []))]
    return [Send("write", {"paper_id": state["paper_id"], "subject": state["subject"], "title": state["title"],
                           "section": s, "taxonomy": state["taxonomy"], "round": state.get("round", 1),
                           "feedback": feedback.get(s["key"])}) for s in to_write]


def write(task: dict) -> dict:
    """One section, from its evidence pack. Runs beside the other sections."""
    result = write_section(task["paper_id"], task["subject"], task["title"], task["section"], task["taxonomy"],
                           task["round"], task.get("feedback"))
    ledger(task["paper_id"], "write", "section", result)
    return {"written": [result], "log": [{"node": "write", "kind": "section", "detail": result}]}


def review(state: PaperState) -> dict:
    problems = check_drafts(state["paper_id"], state["outline"])
    found = review_paper(state["paper_id"], state["subject"], state["outline"])
    verdict = "accept" if found["verdict"] == "accept" and not problems else "revise"
    return {"review": found, "problems": problems, "status": f"reviewed_{verdict}",
            **note_step(state, "review", "verdict", {"verdict": verdict, "problems": problems,
                                                      "summary": found["summary"][:400]})}


def after_review(state: PaperState):
    needs = [s for s in state["review"]["sections"] if s["needs_more_evidence"] and s["queries"]]
    if state["status"] == "reviewed_accept" or state.get("round", 1) >= CFG.max_rounds or not needs:
        return "assemble"
    keys = {s["key"]: s for s in state["outline"]}
    return [Send("gather", {"paper_id": state["paper_id"], "subject": state["subject"], "section": keys[s["key"]],
                            "queries": s["queries"][:2], "round": state["round"] + 1}) for s in needs if s["key"] in keys]


def assemble(state: PaperState) -> dict:
    paper = assemble_paper(state["paper_id"], state["subject"], state["title"], state["outline"], state["taxonomy"])
    html = to_html(paper["markdown"], state["title"])
    set_status(state["paper_id"], "ASSEMBLED", markdown=paper["markdown"], html=html, usage=json.dumps(USAGE))
    return {"paper": {**paper, "html_chars": len(html)}, "status": "awaiting_publication",
            **note_step(state, "assemble", "paper", paper["counts"])}


def publication_review(state: PaperState) -> dict:
    decision = interrupt({"paper_id": state["paper_id"], "title": state["title"], "counts": state["paper"]["counts"],
                          "abstract": state["paper"]["abstract"], "options": ["approve", "reject"]})
    return {"decision": decision, **note_step(state, "publication_review", "decision", decision)}


def after_publication_review(state: PaperState) -> str:
    return "publish" if state["decision"].get("decision") == "approve" else "close"


def publish(state: PaperState) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUTPUT_DIR / state["paper_id"]
    found = rows("SELECT markdown, html FROM survey_papers WHERE paper_id = :p", {"p": state["paper_id"]})[0]
    stem.with_suffix(".md").write_text(found["markdown"])
    stem.with_suffix(".html").write_text(found["html"])
    set_status(state["paper_id"], "PUBLISHED")
    files = {"markdown": str(stem.with_suffix(".md")), "html": str(stem.with_suffix(".html"))}
    return {"status": "published", "paper": {**state["paper"], **files},
            **note_step(state, "publish", "files", files)}


def close(state: PaperState) -> dict:
    set_status(state["paper_id"], "DECLINED")
    return {"status": "declined", **note_step(state, "close", "closed", "declined")}


# ── the graph ────────────────────────────────────────────────────────────────

def build_graph(saver=None):
    graph = StateGraph(PaperState)
    for name, node in [("scope", scope), ("outline_review", outline_review), ("rescope", rescope), ("gather", gather),
                       ("read", read), ("organise", organise), ("write", write), ("review", review),
                       ("assemble", assemble), ("publication_review", publication_review), ("publish", publish),
                       ("close", close)]:
        graph.add_node(name, node)
    graph.add_edge(START, "scope")
    graph.add_edge("scope", "outline_review")
    graph.add_conditional_edges("outline_review", after_outline_review, ["rescope", "close", "gather"])
    graph.add_edge("rescope", "scope")
    graph.add_edge("gather", "read")
    graph.add_edge("read", "organise")
    graph.add_conditional_edges("organise", fan_out_write, ["write"])
    graph.add_edge("write", "review")
    graph.add_conditional_edges("review", after_review, ["assemble", "gather"])
    graph.add_edge("assemble", "publication_review")
    graph.add_conditional_edges("publication_review", after_publication_review, ["publish", "close"])
    graph.add_edge("publish", END)
    graph.add_edge("close", END)
    return graph.compile(checkpointer=saver or InMemorySaver())


_runtime: dict[str, Any] = {}


def durable_graph():
    if "graph" not in _runtime:
        create_survey_tables()
        saver = OracleSaver(pool("checkpoints", max=8), json_size_threshold_mb=0.0)
        saver.setup()
        _runtime["saver"] = saver
        _runtime["graph"] = build_graph(saver)
    return _runtime["graph"]


def config_for(paper_id: str) -> dict:
    """One thread per paper. Parallel branches are capped so a small database is not flooded."""
    return {"configurable": {"thread_id": paper_id}, "max_concurrency": 3}


def outcome(paper_id: str) -> dict:
    snapshot = durable_graph().get_state(config_for(paper_id))
    values = snapshot.values
    waiting = any(t.interrupts for t in snapshot.tasks)
    stopped = [t.name for t in snapshot.tasks if t.error] or (list(snapshot.next) if not waiting else [])
    status = ("awaiting_person" if waiting else "interrupted" if stopped else values.get("status"))
    interrupt_payload = next((t.interrupts[0].value for t in snapshot.tasks if t.interrupts), None)
    return {"paper_id": paper_id, "status": status, "waiting_for_person": waiting, "asked": interrupt_payload,
            "resume_from": stopped, "next": list(snapshot.next), "title": values.get("title"),
            "outline": values.get("outline", []), "taxonomy": values.get("taxonomy"),
            "sources": len(sources_for(paper_id)), "sections": [{k: d[k] for k in ("section_key", "title", "words", "citations", "round")}
                                                                 for d in drafts(paper_id)],
            "review": values.get("review"), "problems": values.get("problems", []), "round": values.get("round", 0),
            "paper": values.get("paper"), "log": values.get("log", []), "usage": dict(USAGE),
            "checkpoints": sum(1 for _ in _runtime["saver"].list(config_for(paper_id)))}


def start_paper(subject: str, audience: str = "researchers and engineers building agent systems",
                paper_id: str | None = None) -> dict:
    paper_id = paper_id or new_id("PAPER")
    durable_graph().invoke({"paper_id": paper_id, "subject": subject, "audience": audience, "rescopes": 0,
                            "round": 0, "sources": [], "written": [], "log": []}, config_for(paper_id))
    return outcome(paper_id)


def resume_paper(paper_id: str, decision: str, note: str = "") -> dict:
    durable_graph().invoke(Command(resume={"decision": decision, "note": note}), config_for(paper_id))
    return outcome(paper_id)


def continue_paper(paper_id: str) -> dict:
    durable_graph().invoke(None, config_for(paper_id))
    return outcome(paper_id)
