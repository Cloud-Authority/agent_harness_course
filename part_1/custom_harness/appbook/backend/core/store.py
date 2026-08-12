"""One substrate for business tables, vectors, memory, cache and checkpoints."""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from backend.config import SHARED_DIR, settings

if str(SHARED_DIR / "seed") not in sys.path:
    sys.path.insert(0, str(SHARED_DIR / "seed"))
from generate_seed_data import DB_PATH, build_sqlite  # noqa: E402

_lock = threading.RLock()
_state: dict[str, Any] = {"ready": False, "error": None}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def initialize() -> None:
    """Idempotent, additive warm-up. Existing user memory is never reset."""
    with _lock:
        try:
            build_sqlite(DB_PATH)
            with connect() as conn:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS custom_memories (
                  memory_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, memory_type TEXT NOT NULL,
                  content TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_custom_memory_user_type ON custom_memories(user_id,memory_type);
                CREATE TABLE IF NOT EXISTS custom_checkpoints (
                  thread_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS custom_cache (
                  cache_key TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
                  payload TEXT NOT NULL, tokens INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS custom_traces (
                  trace_id TEXT PRIMARY KEY, thread_id TEXT, trace TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS custom_file_storage (
                  file_id TEXT PRIMARY KEY, mime_type TEXT, content TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS custom_agent_sessions (
                  session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'ACTIVE', started_at TEXT NOT NULL, ended_at TEXT);
                CREATE TABLE IF NOT EXISTS custom_scratch_files (
                  session_id TEXT NOT NULL, path TEXT NOT NULL, is_dir INTEGER NOT NULL DEFAULT 0,
                  content BLOB, promote_on_end INTEGER NOT NULL DEFAULT 0,
                  promotion_state TEXT NOT NULL DEFAULT 'N', updated_at TEXT NOT NULL,
                  PRIMARY KEY(session_id,path));
                CREATE TABLE IF NOT EXISTS custom_memory_promotion_queue (
                  queue_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                  path TEXT NOT NULL, chunk TEXT NOT NULL, consumed TEXT NOT NULL DEFAULT 'N',
                  staged_at TEXT NOT NULL, consumed_at TEXT);
                CREATE TABLE IF NOT EXISTS custom_action_audit (
                  action_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, action_type TEXT NOT NULL,
                  payload TEXT NOT NULL, approval_state TEXT NOT NULL,
                  created_at TEXT NOT NULL, approved_at TEXT);
                CREATE TABLE IF NOT EXISTS custom_store_orders (
                  order_id TEXT PRIMARY KEY, customer_name TEXT NOT NULL, email TEXT NOT NULL,
                  order_date TEXT NOT NULL, region TEXT NOT NULL, channel TEXT NOT NULL,
                  status TEXT NOT NULL, total REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS custom_store_order_lines (
                  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  order_id TEXT NOT NULL REFERENCES custom_store_orders(order_id),
                  sku TEXT NOT NULL, variant_id TEXT NOT NULL, location_id TEXT NOT NULL,
                  qty INTEGER NOT NULL, unit_price REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS custom_briefs (
                  brief_id TEXT PRIMARY KEY, user_id TEXT, content TEXT, trace_id TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS custom_schedule (
                  job_name TEXT PRIMARY KEY, cadence TEXT, next_run TEXT, last_run TEXT, status TEXT);
                CREATE TABLE IF NOT EXISTS custom_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                fixture = json.loads((SHARED_DIR / "fixtures" / "memory_fixtures.json").read_text(encoding="utf-8"))
                stamp = datetime.now(timezone.utc).isoformat()
                for kind in ("semantic", "episodic", "procedural"):
                    for index, item in enumerate(fixture[kind]):
                        content = item.get("fact") or item.get("event") or f"{item.get('skill')}: {item.get('steps')}"
                        conn.execute("INSERT OR IGNORE INTO custom_memories VALUES (?,?,?,?,?,?)",
                                     (f"seed-{kind}-{index:02d}", fixture["user"]["id"], kind, content,
                                      json.dumps({**item, "source": "shared_fixture"}), stamp))
                conn.execute("INSERT OR IGNORE INTO custom_schedule VALUES (?,?,?,?,?)",
                             ("erpa_morning_brief", "weekdays 08:00 Europe/London", "next weekday 08:00", None, "scheduled"))
                conn.execute("INSERT OR REPLACE INTO custom_meta VALUES ('fixture_version','1')")
            _state.update({"ready": True, "error": None})
        except Exception as exc:
            _state.update({"ready": False, "error": str(exc)})
            raise


def status() -> dict[str, Any]:
    if settings.live:
        from backend.core.oracle_live import preflight
        try:
            return preflight()
        except Exception as exc:
            return {
                "ready": False,
                "mode": "live",
                "substrate": "Oracle AI Database",
                "error": str(exc),
            }
    try:
        initialize()
        with connect() as conn:
            business = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                        for name in ("products", "variants", "orders", "order_lines")}
            harness = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                       for name in ("custom_memories", "custom_cache", "custom_checkpoints", "custom_traces", "custom_file_storage")}
        return {"ready": True, "mode": settings.mode,
                "substrate": "SQLite single-substrate teaching mirror",
                "business_tables": business, "harness_tables": harness,
                "capabilities": ["relational data", "vectors", "OAMP memory", "semantic cache", "LangGraph checkpoints", "SecureFile ScratchFS mirror"],
                "live_factory": "Oracle thin-mode components are available in core/oracle_live.py" if settings.live else None,
                "idempotent": True}
    except Exception as exc:
        return {"ready": False, "error": str(exc)}


def save_trace(thread_id: str, trace: dict) -> None:
    if settings.live:
        return
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO custom_traces VALUES (?,?,?,?)",
                     (trace["trace_id"], thread_id, json.dumps(trace), datetime.now(timezone.utc).isoformat()))


def latest_trace() -> dict | None:
    if settings.live:
        from backend.core.agent import get_graph

        return getattr(get_graph(), "latest_trace", None)
    initialize()
    with connect() as conn:
        row = conn.execute("SELECT trace FROM custom_traces ORDER BY created_at DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None
