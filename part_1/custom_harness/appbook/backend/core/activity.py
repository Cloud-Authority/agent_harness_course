"""Live database-activity telemetry for the appbook data explorer.

This is deliberately application telemetry rather than database auditing.  It gives
learners a safe, human-readable view of which physical tables an appbook operation
touches while Oracle/SQLite remains the source of truth for the rows themselves.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.config import settings


def _physical(local: str, live: str) -> str:
    return live if settings.live else local


MEMORIES = _physical("custom_memories", "erpa_memories")
SCRATCH = _physical("custom_scratch_files", "erpa_scratch_files")
PROMOTION_QUEUE = _physical("custom_memory_promotion_queue", "erpa_memory_promotion_queue")
CACHE = _physical("custom_cache", settings.cache_table)
CHECKPOINTS = _physical("custom_checkpoints", "checkpoints")
TRACES = _physical("custom_traces", "erpa_traces")
SKILLS = _physical("custom_memories", "erpa_skill_registry")
TOOLS = _physical("custom_memories", "erpa_tool_registry")
SEMANTIC = _physical("products", "erpa_semantic_catalog")
FILES = _physical("custom_file_storage", "erpa_file_storage")
ACTIONS = _physical("custom_action_audit", "erpa_action_audit")
STORE_ORDERS = _physical("custom_store_orders", "erpa_store_orders")
STORE_LINES = _physical("custom_store_order_lines", "erpa_store_order_lines")


class ActivityBroker:
    def __init__(self) -> None:
        self._recent: deque[dict[str, Any]] = deque(maxlen=160)
        self._subscribers: set[asyncio.Queue] = set()
        self._sequence = 0

    def transaction_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def publish(
        self,
        *,
        transaction_id: str,
        table: str,
        operation: str,
        status: str,
        route: str,
        row_key: str | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        self._sequence += 1
        event = {
            "sequence": self._sequence,
            "transaction_id": transaction_id,
            "table": table.lower(),
            "operation": operation.upper(),
            "status": status,
            "route": route,
            "row_key": row_key,
            "detail": detail,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        self._recent.appendleft(event)
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        return event

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=96)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        return list(self._recent)[: min(max(limit, 1), 100)]


activity = ActivityBroker()


def operations_for(method: str, path: str) -> list[dict[str, str | None]]:
    """Map public app operations to the physical tables they access."""
    method = method.upper()
    row_key: str | None = None
    operations: list[tuple[str, str]] = []

    if path.startswith("/api/data_explorer/tables/") and path.endswith("/rows"):
        table = path.split("/")[4]
        operations = [(table, "READ")]
    elif path.startswith("/api/storefront/catalog"):
        operations = [("products", "READ"), ("variants", "READ"), ("inventory", "READ")]
    elif path.startswith("/api/storefront/products/"):
        operations = [("products", "READ"), ("variants", "READ"), ("inventory", "READ"), ("locations", "READ")]
    elif path.startswith("/api/storefront/checkout"):
        operations = [("inventory", "WRITE"), (STORE_ORDERS, "WRITE"), (STORE_LINES, "WRITE")]
    elif path.startswith("/api/storefront/chat") or path.startswith("/api/mission_control/chat") or path.startswith("/api/the_loop/"):
        operations = [
            ("products", "READ"), ("variants", "READ"), ("inventory", "READ"),
            (MEMORIES, "READ"), (SKILLS, "READ"), (TOOLS, "READ"), (SEMANTIC, "READ"),
            (MEMORIES, "WRITE"), (CHECKPOINTS, "WRITE"), (TRACES, "WRITE"), (CACHE, "WRITE"),
        ]
    elif path.startswith("/api/memory_layer/chat"):
        operations = [(MEMORIES, "READ"), (SCRATCH, "WRITE"), (MEMORIES, "WRITE"), (CHECKPOINTS, "WRITE"), (TRACES, "WRITE")]
    elif path.startswith("/api/memory_layer/session/start"):
        operations = [(_physical("custom_agent_sessions", "erpa_agent_sessions"), "WRITE"), (SCRATCH, "WRITE")]
    elif path.startswith("/api/memory_layer/session/") and method == "GET":
        operations = [(MEMORIES, "READ"), (SCRATCH, "READ")]
    elif path.startswith("/api/memory_layer/recall") or (path == "/api/memory_layer/status" and method == "GET"):
        operations = [(MEMORIES, "READ"), (SCRATCH, "READ")]
    elif path.startswith("/api/memory_layer/scratch/write"):
        operations = [(SCRATCH, "WRITE")]
    elif path.startswith("/api/memory_layer/session/end") or path.startswith("/api/mission_control/sessions/"):
        operations = [(SCRATCH, "READ"), (PROMOTION_QUEUE, "WRITE"), (MEMORIES, "WRITE")]
    elif path.startswith("/api/memory_layer/") and method in {"PATCH", "DELETE"}:
        row_key = path.rsplit("/", 1)[-1]
        operations = [(MEMORIES, "WRITE")]
    elif path.startswith("/api/memory_layer/write"):
        operations = [(MEMORIES, "WRITE")]
    elif path.startswith("/api/cache/clear"):
        operations = [(CACHE, "WRITE")]
    elif path.startswith("/api/cache/"):
        operations = [(CACHE, "READ"), (CACHE, "WRITE")]
    elif path.startswith("/api/semantic_layer/"):
        operations = [(SEMANTIC, "READ"), ("products", "READ"), ("variants", "READ"), ("orders", "READ"), ("order_lines", "READ")]
    elif path.startswith("/api/retrieval/"):
        operations = [(SEMANTIC, "READ")]
    elif path.startswith("/api/skills/"):
        operations = [(SKILLS, "READ")]
    elif path.startswith("/api/tools_and_mcp/"):
        operations = [(TOOLS, "READ"), ("products", "READ"), ("inventory", "READ")]
    elif path.startswith("/api/mission_control/actions/"):
        row_key = path.split("/")[4] if len(path.split("/")) > 4 else None
        operations = [(ACTIONS, "WRITE")]
    elif path.startswith("/api/mission_control/files/"):
        row_key = path.rsplit("/", 1)[-1]
        operations = [(FILES, "READ")]
    elif path.startswith("/api/mission_control/schedule/"):
        operations = [("products", "READ"), ("inventory", "READ"), (MEMORIES, "WRITE"), (TRACES, "WRITE")]
    elif path.startswith("/api/foundation/"):
        operations = [("products", "READ"), ("variants", "READ"), ("orders", "READ"), ("order_lines", "READ")]

    # A single request should not create duplicate table/operation pulses.
    seen: set[tuple[str, str]] = set()
    result = []
    for table, operation in operations:
        key = (table.lower(), operation)
        if key not in seen:
            result.append({"table": table.lower(), "operation": operation, "row_key": row_key})
            seen.add(key)
    return result
