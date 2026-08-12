"""Semantic cache located before context assembly (the harness boundary)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.config import settings
from backend.core import store


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


class BoundarySemanticCache:
    """Use OracleSemanticCache live and the deterministic mirror locally."""

    threshold = 0.82
    answer_contract = "grounded-v2"

    def _data_version(self) -> str:
        if not settings.live:
            return "fixture-v1"
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT
                  (SELECT COUNT(*)||':'||NVL(SUM(on_hand),0)||':'||NVL(SUM(reorder_point),0) FROM inventory) inventory,
                  (SELECT COUNT(*)||':'||NVL(SUM(qty),0) FROM purchase_orders WHERE status='open') open_pos,
                  (SELECT COUNT(*)||':'||NVL(SUM(qty),0)||':'||NVL(TO_CHAR(MAX(order_date),'YYYYMMDD'),'none')
                     FROM orders JOIN order_lines USING(order_id)) sales
                  FROM dual""")
                row = cursor.fetchone()
        finally:
            connection.close()
        return hashlib.sha256(json.dumps(row, default=str).encode()).hexdigest()[:12]

    def namespace_for(self, user_id: str = settings.user_id) -> str:
        return (
            f"{settings.anthropic_model};thinking={settings.anthropic_thinking};"
            f"{settings.cache_namespace};answer={self.answer_contract};"
            f"tenant={settings.tenant_id};user={user_id};"
            f"data={self._data_version()}"
        )

    @property
    def namespace(self) -> str:
        return self.namespace_for()

    @staticmethod
    def _scoped_prompt(question: str, user_id: str) -> str:
        return f"tenant={settings.tenant_id};user={user_id};question={question.strip()}"

    @staticmethod
    def cacheable(question: str) -> bool:
        text = question.lower()
        return len(text.split()) >= 4 and not any(term in text for term in (
            "morning brief", "remember", "persist", "stop showing", "don't show",
            "do not show", "exclude", "approve", "send", "draft", "schedule",
            "book", "create", "update", "delete", "write",
        ))

    def get(self, question: str, user_id: str = settings.user_id) -> dict[str, Any] | None:
        if not settings.cache_enabled or not self.cacheable(question):
            return None
        if settings.live:
            return self._get_oracle(question, user_id)
        return self._get_local(question)

    def _get_oracle(self, question: str, user_id: str) -> dict[str, Any] | None:
        from backend.core.oracle_live import get_oracle_stack

        namespace = self.namespace_for(user_id)
        generations = get_oracle_stack().semantic_cache.lookup(
            self._scoped_prompt(question, user_id), namespace,
        )
        if not generations:
            return None
        raw = generations[0].text
        try:
            envelope = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            envelope = {"answer": raw, "payload": {}, "original_tokens": 0}
        return {
            "answer": envelope["answer"],
            "payload": envelope.get("payload", {}),
            "original_tokens": envelope.get("original_tokens", 0),
            "similarity": f"Oracle cosine threshold ≤ {settings.cache_score_threshold}",
            "cached_question": "semantic match",
            "namespace": namespace,
        }

    def _get_local(self, question: str) -> dict[str, Any] | None:
        wanted = _tokens(question)
        best: tuple[float, Any] | None = None
        store.initialize()
        with store.connect() as conn:
            for row in conn.execute("SELECT * FROM custom_cache"):
                payload = json.loads(row["payload"])
                if payload.get("_namespace") != self.namespace_for():
                    continue
                candidate = _tokens(row["question"])
                score = len(wanted & candidate) / max(1, len(wanted | candidate))
                if best is None or score > best[0]:
                    best = (score, row)
        if not best or best[0] < self.threshold:
            return None
        row = best[1]
        return {
            "answer": row["answer"],
            "payload": json.loads(row["payload"]),
            "original_tokens": row["tokens"],
            "similarity": round(best[0], 3),
            "cached_question": row["question"],
        }

    def put(
        self, question: str, answer: str, payload: dict, tokens: int,
        user_id: str = settings.user_id,
    ) -> None:
        if not settings.cache_enabled or not self.cacheable(question):
            return
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack
            from langchain_core.outputs import Generation

            envelope = json.dumps(
                {"answer": answer, "payload": payload, "original_tokens": tokens},
                default=str,
                separators=(",", ":"),
            )
            get_oracle_stack().semantic_cache.update(
                self._scoped_prompt(question, user_id),
                self.namespace_for(user_id),
                [Generation(text=envelope)],
            )
            return
        payload = {**payload, "_namespace": self.namespace_for(user_id)}
        key = hashlib.sha256((self.namespace_for(user_id) + ":" + " ".join(sorted(_tokens(question)))).encode()).hexdigest()
        with store.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO custom_cache VALUES (?,?,?,?,?,?)",
                (key, question, answer, json.dumps(payload), tokens, datetime.now(timezone.utc).isoformat()),
            )

    def clear(self) -> int | None:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            count = self._oracle_count()
            get_oracle_stack().semantic_cache.clear()
            return count
        store.initialize()
        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM custom_cache").fetchone()[0]
            conn.execute("DELETE FROM custom_cache")
        return count

    def _oracle_count(self) -> int | None:
        from backend.core.oracle_live import get_oracle_stack

        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]*", settings.cache_table):
            raise ValueError("ERPA_CACHE_TABLE must be a simple Oracle identifier")
        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {settings.cache_table}")
                    return int(cursor.fetchone()[0])
                except Exception as exc:
                    error = exc.args[0] if exc.args else None
                    if getattr(error, "code", None) == 942:  # table is created lazily
                        return 0
                    raise
        finally:
            connection.close()

    def status(self) -> dict[str, Any]:
        if settings.live:
            return {
                "enabled": settings.cache_enabled,
                "placement": "before assemble_context",
                "implementation": "langchain_oracledb.OracleSemanticCache",
                "table": settings.cache_table,
                "namespace": self.namespace,
                "entries": self._oracle_count(),
                "distance_strategy": "COSINE",
                "score_threshold": settings.cache_score_threshold,
                "invalidation": "model + thinking + prompt + tenant + user + business-data fingerprint",
                "embedding": f"Oracle VECTOR_EMBEDDING({settings.oamp_indb_embed_model})",
            }
        store.initialize()
        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM custom_cache").fetchone()[0]
        return {
            "enabled": settings.cache_enabled,
            "placement": "before assemble_context",
            "implementation": "deterministic SQLite teaching mirror",
            "entries": count,
            "similarity_threshold": self.threshold,
        }


semantic_cache = BoundarySemanticCache()
