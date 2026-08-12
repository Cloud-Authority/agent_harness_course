"""Memory providers for the local mirror and the live OAMP 26.6 runtime."""
from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from backend.config import SHARED_DIR, settings
from backend.core import store

try:
    from langsmith import traceable  # type: ignore
except ImportError:  # zero-credential/minimal workshop environment
    def traceable(*_args, **_kwargs):
        def decorate(function: Callable):
            @wraps(function)
            def wrapped(*args, **kwargs):
                return function(*args, **kwargs)
            return wrapped
        return decorate


WORKSHOP_TYPES = ("working", "episodic", "semantic", "procedural")
OAMP_TYPES = {
    "working": "memory",
    "episodic": "memory",
    "semantic": "preference",
    "procedural": "guideline",
}
AGENT_ID = settings.agent_id
TENANT_ID = settings.tenant_id
OAMP_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="erpa-oamp")


def _oamp_call(function: Callable, *args: Any, **kwargs: Any) -> Any:
    """Keep synchronous OAMP calls outside FastAPI/Jupyter asyncio threads."""
    return OAMP_EXECUTOR.submit(function, *args, **kwargs).result()


def _oamp_type(memory_type: str, metadata: dict | None = None) -> str:
    if memory_type == "semantic" and (metadata or {}).get("kind") != "preference":
        return "fact"
    return OAMP_TYPES[memory_type]


class LocalOAMPMemoryProvider:
    """Deterministic SQLite teaching mirror of the live OAMP provider contract."""

    @traceable(name="memory.read.oamp", run_type="retriever")
    def recall(
        self,
        query: str,
        user_id: str = "planner-01",
        limit: int = 8,
        *,
        thread_id: str = "demo-thread",
    ) -> list[dict[str, Any]]:
        del thread_id
        store.initialize()
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        with store.connect() as conn:
            rows = conn.execute("SELECT * FROM custom_memories WHERE user_id=?", (user_id,)).fetchall()
        items = [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]
        ranked = sorted(items, key=lambda item: (
            len(words & set(re.findall(r"[a-z0-9]+", item["content"].lower()))),
            item["memory_type"] == "episodic"), reverse=True)
        return ranked if "brief" in query.lower() else ranked[:limit]

    @traceable(name="memory.write.oamp", run_type="tool")
    def write(
        self,
        memory_type: str,
        content: str,
        user_id: str = "planner-01",
        metadata: dict | None = None,
        *,
        thread_id: str | None = None,
        ttl_days: int | None = None,
    ) -> dict:
        del thread_id, ttl_days
        if memory_type not in WORKSHOP_TYPES:
            raise ValueError("memory_type must be working, episodic, semantic or procedural")
        store.initialize()
        with store.connect() as conn:
            duplicate = conn.execute(
                "SELECT * FROM custom_memories WHERE user_id=? AND memory_type=? AND lower(content)=lower(?)",
                (user_id, memory_type, content),
            ).fetchone()
            if duplicate:
                return {**dict(duplicate), "metadata": json.loads(duplicate["metadata"]), "deduplicated": True}
            item = {
                "memory_id": uuid.uuid4().hex,
                "user_id": user_id,
                "memory_type": memory_type,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            conn.execute(
                "INSERT INTO custom_memories VALUES (?,?,?,?,?,?)",
                (item["memory_id"], user_id, memory_type, content, json.dumps(item["metadata"]), item["created_at"]),
            )
        return item

    def list(self, user_id: str = "planner-01") -> dict[str, list[dict]]:
        store.initialize()
        result = {kind: [] for kind in WORKSHOP_TYPES}
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_memories WHERE user_id=? ORDER BY created_at,memory_id",
                (user_id,),
            ).fetchall()
        for row in rows:
            result[row["memory_type"]].append({**dict(row), "metadata": json.loads(row["metadata"])})
        return result

    def exclusions(self, user_id: str = "planner-01") -> list[str]:
        return _find_exclusions(self.list(user_id))

    def context_card(self, thread_id: str, user_id: str = "planner-01") -> str:
        del thread_id, user_id
        return ""

    def persist_assistant_message(self, thread_id: str, content: str, user_id: str = "planner-01") -> None:
        del thread_id, content, user_id

    def wait_for_extraction(self, timeout: float = 300.0) -> None:
        del timeout

    def update(self, memory_id: str, content: str, *, ttl_days: int | None = None) -> str:
        del ttl_days
        store.initialize()
        with store.connect() as conn:
            conn.execute("UPDATE custom_memories SET content=? WHERE memory_id=?", (content, memory_id))
        return memory_id

    def delete(self, memory_id: str) -> int:
        store.initialize()
        with store.connect() as conn:
            cursor = conn.execute("DELETE FROM custom_memories WHERE memory_id=?", (memory_id,))
        return cursor.rowcount

    def status(self) -> dict[str, Any]:
        memories = self.list()
        return {
            "ready": True,
            "provider": type(self).__name__,
            "implementation": "OAMP-shaped SQLite teaching mirror",
            "counts": {kind: len(items) for kind, items in memories.items()},
            "memories": memories,
            "features": ["typed memory", "recall", "update", "delete"],
        }


class LiveOAMPMemoryProvider:
    """Adapter over Oracle Agent Memory whose public methods are used by the graph."""

    def __init__(self) -> None:
        self._seeded_users: set[str] = set()
        self._lock = threading.RLock()

    @property
    def _stack(self) -> Any:
        from backend.core.oracle_live import get_oracle_stack
        return get_oracle_stack()

    def _ensure_profile_and_seed(self, user_id: str) -> None:
        with self._lock:
            if user_id in self._seeded_users:
                return
            memory, oamp_store = self._stack.oamp, self._stack.oamp_store
            metadata = {"tenant_id": TENANT_ID, "source": "workshop"}
            if oamp_store.get("user_profile", user_id) is None:
                _oamp_call(memory.add_user, user_id, "Kata merchandise planner", metadata=metadata)
            if oamp_store.get("agent_profile", AGENT_ID) is None:
                _oamp_call(memory.add_agent,
                    AGENT_ID,
                    "Enterprise retail planning assistant for grounded merchandise decisions",
                    metadata=metadata,
                )
            fixture = json.loads((SHARED_DIR / "fixtures" / "memory_fixtures.json").read_text(encoding="utf-8"))
            if fixture["user"]["id"] == user_id:
                for workshop_type in ("semantic", "episodic", "procedural"):
                    for index, item in enumerate(fixture[workshop_type]):
                        memory_id = f"seed-{workshop_type}-{index:02d}"
                        oamp_type = _oamp_type(workshop_type, item)
                        if oamp_store.get(oamp_type, memory_id) is not None:
                            continue
                        content = item.get("fact") or item.get("event") or f"{item.get('skill')}: {item.get('steps')}"
                        _oamp_call(memory.add_memory,
                            content,
                            memory_type=oamp_type,
                            memory_id=memory_id,
                            user_id=user_id,
                            agent_id=AGENT_ID,
                            metadata={
                                **metadata,
                                **item,
                                "workshop_type": workshop_type,
                                "source": "shared_fixture",
                            },
                            ttl_days=settings.oamp_max_ttl_days,
                        )
                policy_id = "seed-procedural-policy"
                if oamp_store.get("guideline", policy_id) is None:
                    from oracleagentmemory.core.retention import TimeToLiveAnchor

                    policy_chunks = [
                        "Restock core products below two weeks of cover; seasonal products require an exit-date check.",
                        "A restock recommendation must include SKU, cover weeks, supplier lead time, quantity, and rationale.",
                        "Do not re-raise an inventory issue when an open purchase order or accepted action already covers it.",
                    ]
                    oamp_store.add(
                        contents=["\n\n".join(policy_chunks)],
                        record_type="guideline",
                        index_texts=[policy_chunks],
                        record_ids=policy_id,
                        user_ids=user_id,
                        agent_ids=AGENT_ID,
                        metadata={
                            **metadata,
                            "workshop_type": "procedural",
                            "source": "chunked_merchandising_policy",
                            "policy_code": "ERPA-RESTOCK-01",
                            "version": 1,
                        },
                        ttl_days=settings.oamp_max_ttl_days,
                        ttl_anchor=TimeToLiveAnchor.CREATED_AT,
                    )
            self._seeded_users.add(user_id)

    def _thread(self, thread_id: str, user_id: str) -> Any:
        self._ensure_profile_and_seed(user_id)
        memory = self._stack.oamp
        try:
            return _oamp_call(memory.get_thread, thread_id)
        except KeyError:
            return _oamp_call(memory.create_thread,
                thread_id=thread_id,
                user_id=user_id,
                agent_id=AGENT_ID,
                metadata={"tenant_id": TENANT_ID, "channel": "appbook", "source": "harness"},
                context_card_token_limit=6000,
                context_card_type_search_concurrency=4,
            )

    @staticmethod
    def _record(item: Any) -> dict[str, Any]:
        record = getattr(item, "record", item)
        metadata = dict(getattr(record, "metadata", None) or {})
        oamp_type = getattr(record, "record_type", "memory")
        workshop_type = metadata.get("workshop_type") or {
            "preference": "semantic",
            "fact": "semantic",
            "guideline": "procedural",
            "memory": "episodic",
        }.get(oamp_type, "episodic")
        return {
            "memory_id": getattr(record, "id", getattr(item, "id", "")),
            "user_id": getattr(record, "user_id", None),
            "memory_type": workshop_type,
            "oamp_record_type": oamp_type,
            "content": getattr(record, "content", getattr(item, "content", "")) or "",
            "metadata": metadata,
            "created_at": getattr(record, "timestamp", getattr(item, "timestamp", None)),
            "distance": getattr(item, "distance", None),
        }

    @traceable(name="memory.read.oamp", run_type="retriever")
    def recall(
        self,
        query: str,
        user_id: str = "planner-01",
        limit: int = 8,
        *,
        thread_id: str = "demo-thread",
    ) -> list[dict[str, Any]]:
        from oracleagentmemory.apis import Message

        thread = self._thread(thread_id, user_id)
        _oamp_call(thread.add_messages, [
            Message(
                role="user",
                content=query,
                metadata={"tenant_id": TENANT_ID, "channel": "appbook", "source": "user_turn"},
            )
        ])
        results = _oamp_call(self._stack.oamp.search,
            query,
            user_id=user_id,
            agent_id=AGENT_ID,
            exact_user_match=True,
            exact_agent_match=True,
            exact_thread_match=False,
            max_results=limit,
            record_types=["memory", "guideline", "fact", "preference"],
            metadata_filter={"tenant_id": TENANT_ID},
        )
        return [self._record(item) for item in results]

    @traceable(name="memory.write.oamp", run_type="tool")
    def write(
        self,
        memory_type: str,
        content: str,
        user_id: str = "planner-01",
        metadata: dict | None = None,
        *,
        thread_id: str | None = None,
        ttl_days: int | None = None,
    ) -> dict:
        if memory_type not in WORKSHOP_TYPES:
            raise ValueError("memory_type must be working, episodic, semantic or procedural")
        self._ensure_profile_and_seed(user_id)
        existing = _oamp_call(self._stack.oamp.search,
            content,
            user_id=user_id,
            agent_id=AGENT_ID,
            exact_user_match=True,
            exact_agent_match=True,
            max_results=5,
            record_types=[_oamp_type(memory_type, metadata)],
            metadata_filter={"tenant_id": TENANT_ID},
        )
        for item in existing:
            record = self._record(item)
            if record["content"].casefold() == content.casefold():
                return {**record, "deduplicated": True}
        ttl = ttl_days if ttl_days is not None else {
            "working": 7,
            "episodic": 180,
            "semantic": settings.oamp_max_ttl_days,
            "procedural": settings.oamp_max_ttl_days,
        }[memory_type]
        oamp_type = _oamp_type(memory_type, metadata)
        add_kwargs: dict[str, Any] = {
            "memory_type": oamp_type,
            "user_id": user_id,
            "agent_id": AGENT_ID,
            "metadata": {
                "tenant_id": TENANT_ID,
                "channel": "appbook",
                "source": "manual_write",
                "workshop_type": memory_type,
                **(metadata or {}),
            },
            "ttl_days": ttl,
        }
        if thread_id is not None:
            add_kwargs["thread_id"] = thread_id
        memory_id = _oamp_call(self._stack.oamp.add_memory,
            content,
            **add_kwargs,
        )
        return {
            "memory_id": memory_id,
            "user_id": user_id,
            "memory_type": memory_type,
            "oamp_record_type": oamp_type,
            "content": content,
            "metadata": metadata or {},
            "ttl_days": ttl,
            "deduplicated": False,
        }

    def list(self, user_id: str = "planner-01") -> dict[str, list[dict]]:
        self._ensure_profile_and_seed(user_id)
        result = {kind: [] for kind in WORKSHOP_TYPES}
        for oamp_type in ("memory", "guideline", "fact", "preference"):
            records = self._stack.oamp_store.list(
                oamp_type,
                user_id=user_id,
                agent_id=AGENT_ID,
                metadata_filter={"tenant_id": TENANT_ID},
            )
            for record in records:
                item = self._record(record)
                result[item["memory_type"]].append(item)
        return result

    def exclusions(self, user_id: str = "planner-01") -> list[str]:
        return _find_exclusions(self.list(user_id))

    def context_card(self, thread_id: str, user_id: str = "planner-01") -> str:
        card = _oamp_call(self._thread(thread_id, user_id).get_context_card,
            fallback_message_count=6,
            max_relevant_results=8,
            max_recent_messages=4,
            min_relevant_results_by_type={"preference": 1, "guideline": 1, "fact": 1},
        )
        return card.content

    def persist_assistant_message(self, thread_id: str, content: str, user_id: str = "planner-01") -> None:
        from oracleagentmemory.apis import Message
        _oamp_call(self._thread(thread_id, user_id).add_messages, [
            Message(
                role="assistant",
                content=content,
                metadata={"tenant_id": TENANT_ID, "channel": "appbook", "source": "agent_turn"},
            )
        ])

    def wait_for_extraction(self, timeout: float = 300.0) -> None:
        _oamp_call(self._stack.oamp.wait_for_memory_extraction, timeout=timeout)

    def update(self, memory_id: str, content: str, *, ttl_days: int | None = None) -> str:
        from oracleagentmemory.core.retention import TimeToLiveAnchor
        return _oamp_call(self._stack.oamp.update_memory,
            memory_id,
            content=content,
            ttl_days=ttl_days,
            ttl_anchor=TimeToLiveAnchor.CREATED_AT,
        )

    def delete(self, memory_id: str) -> int:
        return _oamp_call(self._stack.oamp.delete_memory, memory_id)

    def status(self) -> dict[str, Any]:
        memories = self.list()
        return {
            "ready": True,
            "provider": type(self).__name__,
            "implementation": "oracleagentmemory.OracleAgentMemory",
            "version": "26.6.0",
            "search_strategy": self._stack.search_strategy,
            "counts": {kind: len(items) for kind, items in memories.items()},
            "memories": memories,
            "features": [
                "background extraction",
                "context cards",
                "custom extraction instructions",
                "metadata inheritance and filtering",
                "exact user and agent scope matching",
                "typed manual memories",
                "caller-owned chunked indexing",
                "TTL retention",
                "update and delete",
            ],
        }


def _find_exclusions(memories: dict[str, list[dict]]) -> list[str]:
    values = []
    for group in memories.values():
        for item in group:
            text = item["content"].lower()
            if "accessories" in text and any(word in text for word in ("exclude", "stop", "omit")):
                values.append("Accessories")
    return sorted(set(values))


def make_memory_provider() -> LocalOAMPMemoryProvider | LiveOAMPMemoryProvider:
    if settings.live and settings.memory_backend == "oamp":
        return LiveOAMPMemoryProvider()
    return LocalOAMPMemoryProvider()


memory_provider = make_memory_provider()
