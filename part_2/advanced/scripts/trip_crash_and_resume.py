"""Prove that the trip workflow survives a crash between two bookings.

Two processes. The first starts a trip and approves its itinerary with
``TRIP_CRASH_AFTER=book_flight``, so it exits the moment the flight is booked,
before LangGraph has saved that step. The second process continues the same
trip from its last checkpoint: the flight booking is replayed from the
system of record, not made twice, and the hotel and car follow.

    python part_2/advanced/scripts/trip_crash_and_resume.py [trip_id]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ADVANCED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADVANCED))
sys.path.insert(0, str(ADVANCED / "workflow" / "appbook" / "backend"))

TEXT = ("Book me a trip from London to Lisbon, out on 12 October 2026 and back on 15 October 2026. "
        "I need a flight, a hotel and a car. Budget £900.")


def first_process(trip_id: str) -> None:
    from harness import graph
    from shared import oracle
    graph.durable_graph()
    out = graph.start_trip(TEXT, "richmond", trip_id=trip_id)
    print("first process: planned,", out["offers"], "offers; waiting =", out["waiting_for_traveller"], flush=True)
    graph.resume_trip(trip_id, "approve")          # dies inside book_flight
    oracle.close()
    print("first process: this line is never reached")


def second_process(trip_id: str) -> dict:
    from harness import graph
    from shared import oracle
    graph.durable_graph()
    before = graph.outcome(trip_id)
    print("second process: found the trip", before["status"], "resume from", before["resume_from"],
          "| bookings so far", [(b["component"], b["status"]) for b in before["bookings"]], flush=True)
    after = graph.continue_trip(trip_id)
    oracle.close()
    return after


if __name__ == "__main__":
    trip = sys.argv[1] if len(sys.argv) > 1 else "TRIP-crash-demo"
    if os.environ.get("TRIP_CRASH_AFTER"):
        first_process(trip)
        sys.exit(0)
    child = subprocess.run([sys.executable, __file__, trip],
                           env={**os.environ, "TRIP_CRASH_AFTER": "book_flight", "TRIP_CRASH_HARD": "1"})
    print("first process exit code:", child.returncode, "(3 means it died on purpose)")
    result = second_process(trip)
    replayed = [entry for entry in result["log"] if entry["node"] == "book_flight" and entry["kind"] == "booked"]
    print("second process: status", result["status"], "| bookings",
          [(b["component"], b["status"], b["confirmation"]) for b in result["bookings"]])
    print("flight booking replayed:", replayed[-1]["detail"].get("replayed") if replayed else None)
    print(json.dumps({"status": result["status"], "checkpoints": result["checkpoints"],
                      "confirmed": sum(b["status"] == "CONFIRMED" for b in result["bookings"])}))
