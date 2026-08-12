"""A deliberately small, comparable recall → decide → write trace contract."""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class TurnTrace:
    build: str
    question: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.perf_counter)
    spans: list[dict[str, Any]] = field(default_factory=list)
    recalled: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    written: list[dict[str, Any]] = field(default_factory=list)
    cache_hit: bool = False
    tokens: int = 0

    @contextmanager
    def span(self, name: str, kind: str, **attributes: Any) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        item: dict[str, Any] = {"name": name, "kind": kind, "attributes": attributes}
        try:
            yield item
            item["status"] = "ok"
        except Exception as exc:
            item.update({"status": "error", "error": str(exc)})
            raise
        finally:
            item["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            self.spans.append(item)

    def summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "build": self.build,
            "shape": "recall → decide → write",
            "question": self.question,
            "recalled": self.recalled,
            "decision": self.decision,
            "written": self.written,
            "cache_hit": self.cache_hit,
            "tokens": self.tokens,
            "latency_ms": round((time.perf_counter() - self.started) * 1000, 3),
            "spans": self.spans,
        }
