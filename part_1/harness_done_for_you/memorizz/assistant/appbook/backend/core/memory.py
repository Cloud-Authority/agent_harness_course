"""The four memory types exposed by the MemoRizz MemAgent."""
from __future__ import annotations

import re
from typing import Any

from backend.core import store


class MemoRizzMemory:
    def recall(self, query: str, user_id: str = "planner-01") -> list[dict[str, Any]]:
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        memories = store.list_memories(user_id)
        ranked = sorted(memories, key=lambda m: len(words & set(re.findall(r"[a-z0-9]+", m["content"].lower()))), reverse=True)
        # Briefs need the whole preference/action set; other turns use top matches.
        return ranked if "brief" in query.lower() else ranked[:6]

    def remember(self, memory_type: str, content: str, *, user_id: str = "planner-01", metadata: dict | None = None) -> dict:
        existing = store.list_memories(user_id, memory_type)
        if any(item["content"].lower() == content.lower() for item in existing):
            return {**next(item for item in existing if item["content"].lower() == content.lower()), "deduplicated": True}
        return store.add_memory(user_id, memory_type, content, metadata)

    def all(self, user_id: str = "planner-01") -> dict[str, list[dict]]:
        return {kind: store.list_memories(user_id, kind) for kind in ("working", "episodic", "semantic", "procedural")}

    def exclusions(self, user_id: str = "planner-01") -> list[str]:
        values = []
        for item in store.list_memories(user_id):
            if "accessories" in item["content"].lower() and any(
                word in item["content"].lower() for word in ("stop", "exclude", "omit")
            ):
                values.append("Accessories")
        return sorted(set(values))
