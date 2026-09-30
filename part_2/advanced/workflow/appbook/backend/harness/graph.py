"""The durable graph: search in parallel, plan, pause for the traveller, book as a saga, resume."""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langgraph_oracledb.checkpoint.oracle import OracleSaver

from shared.oracle import execute, pool

from .bookings import ProviderError, all_bookings, book, cancel, confirmed_bookings
from .config import CFG
from .memory import recall, remember
from .planning import plan_itinerary, understand_request
from .search import find_offers
from .tables import create_trip_tables, ledger, new_id

COMPONENTS = ("flight", "hotel", "car")


def merge_offers(current: dict | None, update: dict | None) -> dict:
    """Parallel search nodes each add their own component."""
    return {**(current or {}), **(update or {})}


class TripState(TypedDict, total=False):
    trip_id: str
    traveller_id: str
    text: str
    today: str
    preferences: list[str]
    request: dict
    offers: Annotated[dict, merge_offers]
    itinerary: dict
    note: str
    replans: int
    decision: dict
    bookings: Annotated[list, add]
    attempts: int
    failed: str
    questions: list[str]
    status: str
    log: Annotated[list, add]


def note_step(state: TripState, node: str, kind: str, detail: Any) -> dict:
    ledger(state["trip_id"], node, kind, detail)
    return {"log": [{"node": node, "kind": kind, "detail": detail}]}


class Crashed(RuntimeError):
    """Stands in for a process that died: the step's work is committed, its checkpoint is not."""


def maybe_crash(node: str) -> None:
    """For the resume lesson: stop here, after the work but before the checkpoint.

    With ``TRIP_CRASH_HARD=1`` the process really exits, which is what the
    two-process script does. Otherwise the step raises, which LangGraph treats
    the same way: nothing of this step is saved.
    """
    if CFG.crash_after == node:
        if os.getenv("TRIP_CRASH_HARD") == "1":
            sys.stdout.flush()
            os._exit(3)
        raise Crashed(f"the process died inside {node}")


# ── nodes ────────────────────────────────────────────────────────────────────

def recall_preferences(state: TripState) -> dict:
    found = recall(state["traveller_id"], state["text"])
    return {"preferences": found, **note_step(state, "recall_preferences", "memory", found)}


def understand(state: TripState) -> dict:
    request = understand_request(state["text"], state["preferences"], state["today"])
    changed = execute("UPDATE trip_requests SET parsed = :p, status = 'UNDERSTOOD', updated_at = SYSTIMESTAMP "
                      "WHERE trip_id = :id", {"p": json.dumps(request), "id": state["trip_id"]})
    if not changed:
        execute("INSERT INTO trip_requests (trip_id, traveller_id, request, parsed, status) "
                "VALUES (:id, :u, :r, :p, 'UNDERSTOOD')",
                {"id": state["trip_id"], "u": state["traveller_id"], "r": state["text"], "p": json.dumps(request)})
    status = "needs_answers" if request["questions"] else "searching"
    return {"request": request, "questions": request["questions"], "status": status,
            **note_step(state, "understand", "request", request)}


def after_understand(state: TripState) -> list[str] | str:
    if state["questions"]:
        return "ask_traveller"
    return [f"search_{c}" for c in COMPONENTS if c in state["request"]["wants"]] or "ask_traveller"


def ask_traveller(state: TripState) -> dict:
    questions = state.get("questions") or ["What would you like booked?"]
    return {"status": "needs_answers", "questions": questions,
            **note_step(state, "ask_traveller", "question", questions)}


def searcher(component: str):
    """One search node per component; they run in parallel."""
    def search(state: TripState) -> dict:
        offers = find_offers(state["trip_id"], component, state["request"])
        if not offers:
            offers = find_offers(state["trip_id"], component, state["request"], wider=True)
        return {"offers": {component: offers},
                **note_step(state, f"search_{component}", "offers",
                            [{k: o[k] for k in ("offer_id", "provider", "total_gbp", "confidence")} for o in offers])}
    search.__name__ = f"search_{component}"
    return search


def join_offers(state: TripState) -> dict:
    missing = [c for c in state["request"]["wants"] if not state["offers"].get(c)]
    if missing:
        questions = [f"No {c} offers were found on the web for these dates. Change the dates or the place?"
                     for c in missing]
        return {"status": "needs_answers", "questions": questions,
                **note_step(state, "join_offers", "missing", missing)}
    counts = {c: len(v) for c, v in state["offers"].items()}
    return {"status": "planning", **note_step(state, "join_offers", "counts", counts)}


def after_join(state: TripState) -> str:
    return "plan" if state["status"] == "planning" else END


def plan(state: TripState) -> dict:
    itinerary = plan_itinerary(state["request"], state["preferences"], state["offers"], state.get("note", ""))
    return {"itinerary": itinerary, "status": "awaiting_traveller",
            **note_step(state, "plan", "itinerary", {"total_gbp": itinerary["total_gbp"],
                                                      "within_budget": itinerary["within_budget"],
                                                      "choices": [(c["component"], c["offer_id"]) for c in itinerary["choices"]]})}


def review(state: TripState) -> dict:
    """The run stops here. Whatever resumes it is the traveller's decision."""
    decision = interrupt({"trip_id": state["trip_id"], "itinerary": state["itinerary"],
                          "options": ["approve", "change", "reject"]})
    return {"decision": decision, "note": decision.get("note", ""),
            **note_step(state, "review", "decision", decision)}


def after_review(state: TripState) -> str:
    verdict = state["decision"].get("decision")
    if verdict == "approve":
        return "book_flight"
    if verdict == "change" and state.get("replans", 0) < CFG.max_replans:
        return "replan"
    return "close"


def replan(state: TripState) -> dict:
    return {"replans": state.get("replans", 0) + 1, "status": "planning",
            **note_step(state, "replan", "note", state.get("note", ""))}


def booker(component: str):
    """One saga step per component, in a fixed order. Each is safe to run twice."""
    def book_step(state: TripState) -> dict:
        if state.get("failed") or component not in state["request"]["wants"]:
            return {}
        choice = next((c for c in state["itinerary"]["choices"] if c["component"] == component), None)
        if choice is None:
            return {"failed": component, "status": "booking_failed",
                    **note_step(state, f"book_{component}", "provider_error", f"{component}: nothing was chosen")}
        try:
            booking = book(state["trip_id"], component, choice["offer"], state.get("attempts", 0))
        except ProviderError as error:
            return {"failed": component, "status": "booking_failed",
                    **note_step(state, f"book_{component}", "provider_error", str(error))}
        result = {"bookings": [booking], **note_step(state, f"book_{component}", "booked", booking)}
        maybe_crash(f"book_{component}")
        return result
    book_step.__name__ = f"book_{component}"
    return book_step


def after_booking(state: TripState) -> str:
    return "compensate" if state.get("failed") else "confirm"


def compensate(state: TripState) -> dict:
    """Undo what was booked, then fall back to the next offer for the failed component."""
    cancelled = []
    for booking in confirmed_bookings(state["trip_id"]):
        cancel(booking["booking_id"], f"{state['failed']} could not be booked")
        cancelled.append(booking["booking_id"])
    failed = state["failed"]
    choice = next((c for c in state["itinerary"]["choices"] if c["component"] == failed), None)
    attempts = state.get("attempts", 0) + 1
    if choice is None or not choice["alternatives"] or attempts >= CFG.max_booking_attempts:
        return {"attempts": attempts, "failed": "", "status": "unbookable",
                **note_step(state, "compensate", "gave_up", {"cancelled": cancelled, "component": failed})}
    known = {o["offer_id"]: o for found in state["offers"].values() for o in found}
    fallback = known[choice["alternatives"][0]]
    new_choice = {**choice, "offer_id": fallback["offer_id"], "offer": fallback,
                  "alternatives": choice["alternatives"][1:],
                  "why": f"Fallback after the provider answered for {choice['offer']['provider']}: {choice['why']}"}
    itinerary = {**state["itinerary"], "choices": [new_choice if c["component"] == failed else c
                                                   for c in state["itinerary"]["choices"]]}
    itinerary["total_gbp"] = round(sum(c["offer"]["total_gbp"] for c in itinerary["choices"]), 2)
    itinerary["within_budget"] = (not state["request"].get("budget_gbp")
                                  or itinerary["total_gbp"] <= state["request"]["budget_gbp"])
    itinerary["caveats"] = [*itinerary.get("caveats", []),
                            f"The first {failed} choice failed at the provider; earlier bookings were cancelled "
                            f"and this plan uses the next best {failed}."]
    return {"attempts": attempts, "failed": "", "itinerary": itinerary, "status": "awaiting_traveller",
            **note_step(state, "compensate", "fallback", {"cancelled": cancelled, "component": failed,
                                                          "now": fallback["offer_id"]})}


def after_compensate(state: TripState) -> str:
    return "review" if state["status"] == "awaiting_traveller" else "close"


def confirm(state: TripState) -> dict:
    bookings = confirmed_bookings(state["trip_id"])
    total = round(sum(b["price_gbp"] or 0 for b in bookings), 2)
    request = state["request"]
    remember(state["traveller_id"], f"Booked {request['destination']} from {request['origin']} for "
                                    f"{request['depart']} to {request['back']}.", kind="fact", source="trip")
    execute("UPDATE trip_requests SET status = 'BOOKED', updated_at = SYSTIMESTAMP WHERE trip_id = :t",
            {"t": state["trip_id"]})
    return {"status": "booked", **note_step(state, "confirm", "confirmed", {"total_gbp": total,
                                                                             "bookings": [b["confirmation"] for b in bookings]})}


def close(state: TripState) -> dict:
    status = state["status"] if state["status"] in {"unbookable", "needs_answers"} else "declined"
    execute("UPDATE trip_requests SET status = :s, updated_at = SYSTIMESTAMP WHERE trip_id = :t",
            {"s": status.upper(), "t": state["trip_id"]})
    return {"status": status, **note_step(state, "close", "closed", status)}


# ── the graph ────────────────────────────────────────────────────────────────

def build_graph(saver=None):
    graph = StateGraph(TripState)
    for name, node in [("recall_preferences", recall_preferences), ("understand", understand),
                       ("ask_traveller", ask_traveller), ("join_offers", join_offers), ("plan", plan),
                       ("review", review), ("replan", replan), ("compensate", compensate),
                       ("confirm", confirm), ("close", close)]:
        graph.add_node(name, node)
    for component in COMPONENTS:
        graph.add_node(f"search_{component}", searcher(component))
        graph.add_node(f"book_{component}", booker(component))
    graph.add_edge(START, "recall_preferences")
    graph.add_edge("recall_preferences", "understand")
    graph.add_conditional_edges("understand", after_understand,
                                ["ask_traveller", *(f"search_{c}" for c in COMPONENTS)])
    graph.add_edge("ask_traveller", END)
    for component in COMPONENTS:
        graph.add_edge(f"search_{component}", "join_offers")
    graph.add_conditional_edges("join_offers", after_join, ["plan", END])
    graph.add_edge("plan", "review")
    graph.add_conditional_edges("review", after_review, ["book_flight", "replan", "close"])
    graph.add_edge("replan", "plan")
    graph.add_edge("book_flight", "book_hotel")
    graph.add_edge("book_hotel", "book_car")
    graph.add_conditional_edges("book_car", after_booking, ["compensate", "confirm"])
    graph.add_conditional_edges("compensate", after_compensate, ["review", "close"])
    graph.add_edge("confirm", END)
    graph.add_edge("close", END)
    return graph.compile(checkpointer=saver or InMemorySaver())


_runtime: dict[str, Any] = {}


def durable_graph():
    """The graph on OracleSaver, built once per process."""
    if "graph" not in _runtime:
        create_trip_tables()
        saver = OracleSaver(pool("checkpoints", max=8), json_size_threshold_mb=0.0)
        saver.setup()
        _runtime["saver"] = saver
        _runtime["graph"] = build_graph(saver)
    return _runtime["graph"]


def config_for(trip_id: str) -> dict:
    """One thread per trip. Parallel branches are capped so a small database is not flooded."""
    return {"configurable": {"thread_id": trip_id}, "max_concurrency": 3}


def outcome(trip_id: str) -> dict:
    """What a caller needs to know after a run: the state and whether it is waiting."""
    snapshot = durable_graph().get_state(config_for(trip_id))
    values = snapshot.values
    waiting = any(t.interrupts for t in snapshot.tasks)
    stopped = [t.name for t in snapshot.tasks if t.error] or (list(snapshot.next) if not waiting else [])
    status = "awaiting_traveller" if waiting else "interrupted" if stopped else values.get("status")
    return {"trip_id": trip_id, "status": status, "resume_from": stopped,
            "waiting_for_traveller": waiting, "next": list(snapshot.next),
            "itinerary": values.get("itinerary"), "questions": values.get("questions", []),
            "bookings": all_bookings(trip_id), "request": values.get("request"),
            "preferences": values.get("preferences", []), "offers": {c: len(v) for c, v in values.get("offers", {}).items()},
            "log": values.get("log", []), "checkpoints": sum(1 for _ in _runtime["saver"].list(config_for(trip_id)))}


def start_trip(text: str, traveller_id: str, trip_id: str | None = None, today: str | None = None) -> dict:
    trip_id = trip_id or new_id("TRIP")
    durable_graph().invoke({"trip_id": trip_id, "traveller_id": traveller_id, "text": text,
                            "today": today or date.today().isoformat(), "replans": 0, "attempts": 0,
                            "offers": {}, "log": []}, config_for(trip_id))
    return outcome(trip_id)


def resume_trip(trip_id: str, decision: str, note: str = "") -> dict:
    """The traveller's decision continues the same run from its checkpoint."""
    durable_graph().invoke(Command(resume={"decision": decision, "note": note}), config_for(trip_id))
    return outcome(trip_id)


def continue_trip(trip_id: str) -> dict:
    """After a crash: run again with no new input. LangGraph picks up at the last checkpoint."""
    durable_graph().invoke(None, config_for(trip_id))
    return outcome(trip_id)
