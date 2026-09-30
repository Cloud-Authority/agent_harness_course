"""The trip workflow's rules, without a model, a search service or a database."""
from __future__ import annotations

from pathlib import Path

import pytest

ADVANCED = Path(__file__).resolve().parents[1]


def load(module: str):
    from conftest import load_harness
    return load_harness("workflow", module)


def test_the_schema_is_closed_for_structured_output():
    llm = load("harness.llm")
    schema = {"type": "object", "properties": {"offers": {"type": "array", "items": {"type": "object", "properties": {
        "price": {"type": "number"}}}}}}
    closed = llm.strict(schema)
    assert closed["additionalProperties"] is False
    assert closed["properties"]["offers"]["items"]["additionalProperties"] is False


def test_parallel_searches_merge_their_components():
    graph = load("harness.graph")
    assert graph.merge_offers({"flight": [1]}, {"hotel": [2]}) == {"flight": [1], "hotel": [2]}
    assert graph.merge_offers(None, {"car": []}) == {"car": []}


def test_understanding_fans_out_only_to_wanted_components():
    graph = load("harness.graph")
    assert graph.after_understand({"questions": ["Where to?"], "request": {"wants": ["flight"]}}) == "ask_traveller"
    assert graph.after_understand({"questions": [], "request": {"wants": ["hotel", "car"]}}) == ["search_hotel", "search_car"]
    assert graph.after_understand({"questions": [], "request": {"wants": []}}) == "ask_traveller"


def test_the_review_routes_by_decision_and_bounds_replans():
    graph = load("harness.graph")
    assert graph.after_review({"decision": {"decision": "approve"}}) == "book_flight"
    assert graph.after_review({"decision": {"decision": "change"}, "replans": 0}) == "replan"
    assert graph.after_review({"decision": {"decision": "change"}, "replans": graph.CFG.max_replans}) == "close"
    assert graph.after_review({"decision": {"decision": "reject"}}) == "close"


def test_a_failed_component_goes_to_compensation():
    graph = load("harness.graph")
    assert graph.after_booking({"failed": "hotel"}) == "compensate"
    assert graph.after_booking({"failed": ""}) == "confirm"


def test_the_plan_keeps_only_offers_that_exist_and_totals_them(monkeypatch):
    planning = load("harness.planning")
    offers = {"flight": [{"offer_id": "OF-a", "provider": "x", "summary": "", "price": 100, "currency": "GBP", "unit": "total",
                          "total_gbp": 100.0, "confidence": "high"}],
              "hotel": [{"offer_id": "OF-b", "provider": "y", "summary": "", "price": 50, "currency": "GBP", "unit": "per_night",
                         "total_gbp": 150.0, "confidence": "medium"}]}
    monkeypatch.setattr(planning, "ask_typed", lambda *a, **k: {
        "choices": [{"component": "flight", "offer_id": "OF-a", "why": "direct", "alternatives": ["OF-zzz", "OF-b"]},
                    {"component": "hotel", "offer_id": "OF-b", "why": "central", "alternatives": []},
                    {"component": "car", "offer_id": "OF-nope", "why": "", "alternatives": []}],
        "total_gbp": 999, "within_budget": False, "summary": "s", "caveats": []})
    plan = planning.plan_itinerary({"budget_gbp": 300}, [], offers)
    assert [c["component"] for c in plan["choices"]] == ["flight", "hotel"]
    assert plan["choices"][0]["alternatives"] == ["OF-b"]
    assert plan["total_gbp"] == 250.0 and plan["within_budget"] is True


def test_the_idempotency_key_changes_with_the_attempt():
    bookings = load("harness.bookings")
    first = bookings.idempotency_key("T", "flight", "OF-1", 0)
    assert first == "T:flight:OF-1:0" and first != bookings.idempotency_key("T", "flight", "OF-1", 1)


def test_the_graph_has_the_shape_the_lesson_describes():
    graph = load("harness.graph")
    drawn = graph.build_graph().get_graph()
    names = {n for n in drawn.nodes if not n.startswith("__")}
    assert {"recall_preferences", "understand", "search_flight", "search_hotel", "search_car", "join_offers", "plan", "review",
            "book_flight", "book_hotel", "book_car", "compensate", "confirm", "close", "replan", "ask_traveller"} <= names
    edges = {(e.source, e.target) for e in drawn.edges}
    assert ("book_flight", "book_hotel") in edges and ("book_hotel", "book_car") in edges
    assert ("search_flight", "join_offers") in edges


def test_a_component_the_model_skipped_gets_the_cheapest_offer(monkeypatch):
    planning = load("harness.planning")
    offers = {"flight": [{"offer_id": "OF-a", "component": "flight", "provider": "x", "summary": "", "price": 100,
                          "currency": "GBP", "unit": "total", "total_gbp": 100.0, "confidence": "high"}],
              "car": [{"offer_id": "OF-c1", "component": "car", "provider": "y", "summary": "", "price": 10,
                       "currency": "GBP", "unit": "per_day", "total_gbp": 30.0, "confidence": "medium"},
                      {"offer_id": "OF-c2", "component": "car", "provider": "z", "summary": "", "price": 12,
                       "currency": "GBP", "unit": "per_day", "total_gbp": 36.0, "confidence": "medium"}]}
    monkeypatch.setattr(planning, "ask_typed", lambda *a, **k: {
        "choices": [{"component": "flight", "offer_id": "OF-a", "why": "", "alternatives": []},
                    {"component": "car", "offer_id": "OF-made-up", "why": "", "alternatives": []}],
        "total_gbp": 0, "within_budget": True, "summary": "s", "caveats": []})
    plan = planning.plan_itinerary({"budget_gbp": 0, "wants": ["flight", "car"]}, [], offers)
    car = next(c for c in plan["choices"] if c["component"] == "car")
    assert car["offer_id"] == "OF-c1" and car["alternatives"] == ["OF-c2"] and plan["total_gbp"] == 130.0
