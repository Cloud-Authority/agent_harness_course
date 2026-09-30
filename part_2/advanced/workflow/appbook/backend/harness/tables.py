"""The workflow's own tables in Oracle AI Database, beside LangGraph's checkpoints.

``TRIP_REQUESTS`` is one row per trip. ``TRIP_EVIDENCE`` keeps every web page
the harness read, so an offer can always be traced to the page it came from.
``TRIP_BOOKINGS`` is the system of record for bookings: it is what the outside
world would hold, so a crash between two bookings must never lose or double a
row. ``TRIP_PROVIDER_FAULTS`` lets a lesson make a provider fail on purpose.
``TRIP_LEDGER`` is the audit trail a traveller could be shown.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from shared.oracle import ddl, execute, rows

TRIP_TABLES = ["trip_requests", "trip_evidence", "trip_offers", "trip_bookings",
               "trip_provider_faults", "trip_ledger"]


def create_trip_tables() -> None:
    ddl("""CREATE TABLE trip_requests (
        trip_id VARCHAR2(40) PRIMARY KEY, traveller_id VARCHAR2(80) NOT NULL,
        request CLOB NOT NULL, parsed CLOB, status VARCHAR2(30) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP, updated_at TIMESTAMP WITH TIME ZONE)""")
    ddl("""CREATE TABLE trip_evidence (
        evidence_id VARCHAR2(40) PRIMARY KEY, trip_id VARCHAR2(40) NOT NULL, component VARCHAR2(20) NOT NULL,
        query VARCHAR2(1000) NOT NULL, url VARCHAR2(2000) NOT NULL, title VARCHAR2(1000),
        snippet VARCHAR2(4000), score NUMBER, fetched_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP)""")
    ddl("""CREATE TABLE trip_offers (
        offer_id VARCHAR2(40) PRIMARY KEY, trip_id VARCHAR2(40) NOT NULL, component VARCHAR2(20) NOT NULL,
        provider VARCHAR2(200), summary VARCHAR2(1000), price NUMBER, currency VARCHAR2(3),
        price_gbp NUMBER, confidence VARCHAR2(10), evidence_id VARCHAR2(40), details CLOB)""")
    ddl("""CREATE TABLE trip_bookings (
        booking_id VARCHAR2(40) PRIMARY KEY, trip_id VARCHAR2(40) NOT NULL, component VARCHAR2(20) NOT NULL,
        offer_id VARCHAR2(40) NOT NULL, provider VARCHAR2(200), idempotency_key VARCHAR2(120) NOT NULL UNIQUE,
        status VARCHAR2(20) NOT NULL, confirmation VARCHAR2(40), price_gbp NUMBER, reason VARCHAR2(1000),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP, cancelled_at TIMESTAMP WITH TIME ZONE)""")
    ddl("""CREATE TABLE trip_provider_faults (
        fault_id VARCHAR2(40) PRIMARY KEY, component VARCHAR2(20) NOT NULL, match VARCHAR2(200) NOT NULL,
        fault VARCHAR2(40) NOT NULL, remaining NUMBER NOT NULL)""")
    ddl("""CREATE TABLE trip_ledger (
        entry_id VARCHAR2(40) PRIMARY KEY, trip_id VARCHAR2(40) NOT NULL, node VARCHAR2(40) NOT NULL,
        kind VARCHAR2(30) NOT NULL, detail CLOB, at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP)""")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ledger(trip_id: str, node: str, kind: str, detail: dict | str) -> None:
    execute("INSERT INTO trip_ledger (entry_id, trip_id, node, kind, detail) VALUES (:1, :2, :3, :4, :5)",
            [new_id("L"), trip_id, node, kind, json.dumps(detail, default=str) if not isinstance(detail, str) else detail])


def trip_ledger(trip_id: str) -> list[dict]:
    return rows("SELECT node, kind, detail, at FROM trip_ledger WHERE trip_id = :t ORDER BY at, entry_id",
                {"t": trip_id})


def reset_trip_tables() -> None:
    """Empty the workflow's tables. Checkpoints are left to LangGraph's own tables."""
    for table in TRIP_TABLES:
        execute(f"DELETE FROM {table}")
