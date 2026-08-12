"""Legacy compatibility store plus the deterministic local teaching profile.

The expanded appbook's production target is Oracle AI Database.  These SQLite tables
keep the acceptance path credential-free; they are never presented as the live Oracle
provider.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.config import SHARED_DIR, settings

_lock = threading.RLock()
_state: dict[str, Any] = {"ready": False, "error": None}


def connect() -> sqlite3.Connection:
    settings.local_memory_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.local_memory_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def initialize() -> None:
    """Create missing collections/tables and seed only absent fixture records."""
    with _lock:
        try:
            with connect() as conn:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                  memory_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, memory_type TEXT NOT NULL,
                  content TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories(user_id,memory_type);
                CREATE TABLE IF NOT EXISTS working_memory (
                  thread_id TEXT PRIMARY KEY, messages TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                  trace_id TEXT PRIMARY KEY, thread_id TEXT, question TEXT, answer TEXT,
                  trace TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                fixture = json.loads((SHARED_DIR / "fixtures" / "memory_fixtures.json").read_text(encoding="utf-8"))
                now = datetime.now(timezone.utc).isoformat()
                for memory_type in ("semantic", "episodic", "procedural"):
                    for index, item in enumerate(fixture[memory_type]):
                        memory_id = f"seed-{memory_type}-{index:02d}"
                        content = item.get("fact") or item.get("event") or f"{item.get('skill')}: {item.get('steps')}"
                        conn.execute(
                            "INSERT OR IGNORE INTO memories VALUES (?,?,?,?,?,?)",
                            (memory_id, fixture["user"]["id"], memory_type, content, json.dumps({**item, "source": "shared_fixture"}), now),
                        )
                conn.execute("INSERT OR REPLACE INTO meta VALUES ('fixture_version','1')")
                conn.commit()
            _state.update({"ready": True, "error": None})
        except Exception as exc:
            _state.update({"ready": False, "error": str(exc)})
            raise


def status() -> dict[str, Any]:
    try:
        initialize()
        with connect() as conn:
            counts = {kind: conn.execute("SELECT COUNT(*) FROM memories WHERE memory_type=?", (kind,)).fetchone()[0]
                      for kind in ("semantic", "episodic", "procedural")}
            working = conn.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
        return {"ready": True, "mode": settings.mode,
                "substrate": "Oracle AI Database via live factory" if settings.live and settings.oracle_configured else "SQLite deterministic teaching profile",
                "collections": {**counts, "working": working},
                "indexes": ["user_id + memory_type", "Oracle vector indexes (live factory)"], "idempotent": True}
    except Exception as exc:
        return {"ready": False, "error": str(exc)}


def add_memory(user_id: str, memory_type: str, content: str, metadata: dict | None = None) -> dict:
    if memory_type not in {"working", "episodic", "semantic", "procedural"}:
        raise ValueError("unknown memory type")
    initialize()
    item = {"memory_id": uuid.uuid4().hex, "user_id": user_id, "memory_type": memory_type,
            "content": content, "metadata": metadata or {}, "created_at": datetime.now(timezone.utc).isoformat()}
    with connect() as conn:
        conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?)",
                     (item["memory_id"], user_id, memory_type, content, json.dumps(item["metadata"]), item["created_at"]))
    return item


def list_memories(user_id: str = "planner-01", memory_type: str | None = None) -> list[dict]:
    initialize()
    sql, params = "SELECT * FROM memories WHERE user_id=?", [user_id]
    if memory_type:
        sql += " AND memory_type=?"
        params.append(memory_type)
    sql += " ORDER BY created_at,memory_id"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]


def save_turn(thread_id: str, question: str, answer: str, trace: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        row = conn.execute("SELECT messages FROM working_memory WHERE thread_id=?", (thread_id,)).fetchone()
        messages = json.loads(row[0]) if row else []
        messages.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
        messages = messages[-12:]
        conn.execute("INSERT OR REPLACE INTO working_memory VALUES (?,?,?)", (thread_id, json.dumps(messages), now))
        conn.execute("INSERT OR REPLACE INTO turns VALUES (?,?,?,?,?,?)",
                     (trace["trace_id"], thread_id, question, answer, json.dumps(trace), now))


def latest_trace() -> dict | None:
    initialize()
    with connect() as conn:
        row = conn.execute("SELECT trace FROM turns ORDER BY created_at DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None
