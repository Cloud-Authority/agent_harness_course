"""LangGraph persistence and scoped long-term memory on Oracle AI Database."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .config import AdvancedSettings, settings as default_settings


# Oracle Free can terminate dedicated sessions when several ONNX inferences run
# concurrently. All in-process Oracle embedding adapters share this narrow lock;
# ordinary SQL and OpenAI calls remain concurrent.
ORACLE_EMBEDDING_LOCK = threading.RLock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class SemanticEncoder:
    """Embedding boundary used by cache and durable knowledge retrieval.

    OpenAI is the live course default. A deterministic feature-hashing encoder is
    retained for tests and outage fallback, and its use is always exposed in status.
    """

    def __init__(
        self,
        course_settings: AdvancedSettings = default_settings,
        *,
        pool: Any = None,
    ) -> None:
        self.settings = course_settings
        self.backend = course_settings.semantic_backend
        self.pool = pool
        self._client: Any = None
        self._lock = threading.RLock()

    def _oracle_embed(self, text: str) -> list[float]:
        with ORACLE_EMBEDDING_LOCK:
            return self._oracle_embed_serial(text)

    def _oracle_embed_serial(self, text: str) -> list[float]:
        model = self.settings.oracle_embed_model
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,122}", model):
            raise ValueError("Unsafe Oracle mining-model identifier")
        for attempt in range(2):
            owned = self.pool is None
            connection = (
                __import__("oracledb").connect(**self.settings.oracle_connect_kwargs())
                if owned
                else self.pool.acquire()
            )
            try:
                lock_acquired = False
                with connection.cursor() as cursor:
                    try:
                        cursor.execute('''SELECT lock_name FROM agent_runtime_locks
                          WHERE lock_name='ONNX_EMBEDDING' FOR UPDATE WAIT 120''')
                        cursor.fetchone()
                        lock_acquired = True
                    except Exception as lock_exc:
                        if "ORA-00942" not in str(lock_exc):
                            raise
                    cursor.execute(
                        f"SELECT VECTOR_EMBEDDING({model} USING :text AS DATA) FROM dual",
                        {"text": str(text)},
                    )
                    vector = [float(value) for value in cursor.fetchone()[0]]
                if lock_acquired:
                    connection.rollback()
                target = self.settings.embedding_dimensions
                if len(vector) > target:
                    raise RuntimeError(
                        f"{model} returns {len(vector)} dimensions; storage expects {target}"
                    )
                if len(vector) < target:
                    vector.extend([0.0] * (target - len(vector)))
                return vector
            except Exception as exc:
                try:
                    connection.rollback()
                except Exception:
                    pass
                if not owned and attempt == 0 and "DPY-4011" in str(exc):
                    try:
                        self.pool.drop(connection)
                    finally:
                        connection = None
                    continue
                raise
            finally:
                if connection is not None:
                    connection.close()
        raise RuntimeError("Oracle embedding retry exhausted")

    @staticmethod
    def _hash_vector(text: str, dimensions: int = 256) -> list[float]:
        vector = [0.0] * dimensions
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        for token in features:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % dimensions
            sign = -1.0 if digest[4] & 1 else 1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]

    def embed(self, text: str) -> list[float]:
        if self.backend == "hash":
            return self._hash_vector(text, self.settings.embedding_dimensions)
        if self.backend == "oracle":
            return self._oracle_embed(text)
        if self.backend != "openai":
            raise ValueError("ADVANCED_SEMANTIC_BACKEND must be openai, oracle, or hash")
        if not self.settings.openai_api_key:
            raise RuntimeError(
                "ADVANCED_SEMANTIC_BACKEND=openai requires OPENAI_API_KEY; set "
                "ADVANCED_SEMANTIC_BACKEND=hash only for the labelled offline fallback"
            )
        with self._lock:
            if self._client is None:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.settings.openai_api_key)
        request: dict[str, Any] = {
            "model": self.settings.openai_embed_model,
            "input": text,
        }
        if self.settings.openai_embed_model.startswith("text-embedding-3"):
            request["dimensions"] = self.settings.embedding_dimensions
        response = self._client.embeddings.create(**request)
        return [float(item) for item in response.data[0].embedding]

    @staticmethod
    def cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(item * item for item in left))
        right_norm = math.sqrt(sum(item * item for item in right))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)


@dataclass
class PersistenceResources:
    """Own the pool, LangGraph checkpointer, and cross-thread store."""

    checkpointer: Any
    store: Any
    backend: str
    pool: Any = None
    oracle_version: str | None = None
    vector_search: bool = False

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close(force=True)


def create_persistence(
    course_settings: AdvancedSettings = default_settings,
    *,
    enable_vector_search: bool = True,
) -> PersistenceResources:
    """Create real Oracle integrations or the explicit test-only memory profile."""

    if course_settings.backend == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore

        return PersistenceResources(
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            backend="memory (non-durable teaching fallback)",
        )
    if course_settings.backend != "oracle":
        raise ValueError("ADVANCED_BACKEND must be oracle or memory")

    course_settings.validate_oracle()
    import oracledb
    from langgraph_oracledb.checkpoint.oracle import OracleSaver
    from langgraph_oracledb.store.oracle import OracleStore

    pool_kwargs = {
        **course_settings.oracle_connect_kwargs(),
        "min": course_settings.ora_pool_min,
        "max": course_settings.ora_pool_max,
        "increment": 1,
    }
    pool = oracledb.create_pool(**pool_kwargs)
    try:
        with pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT version_full FROM product_component_version "
                    "WHERE product LIKE 'Oracle%Database%' FETCH FIRST 1 ROW ONLY"
                )
                row = cursor.fetchone()
                oracle_version = str(row[0]) if row else "unknown"
        checkpointer = OracleSaver(pool, json_size_threshold_mb=0.0)
        checkpointer.setup()
        index = None
        if enable_vector_search:
            vector_encoder = SemanticEncoder(course_settings, pool=pool)

            def embed_batch(texts: Sequence[str]) -> list[list[float]]:
                return [vector_encoder.embed(str(text)) for text in texts]

            index = {
                "embed": embed_batch,
                "dims": course_settings.embedding_dimensions,
                "fields": ["text"],
                "index_type": {
                    "type": "hnsw",
                    "neighbors": 16,
                    "efconstruction": 200,
                    "distance_metric": "COSINE",
                },
            }
        store = OracleStore(pool, index=index)
        store.setup()
        return PersistenceResources(
            checkpointer=checkpointer,
            store=store,
            backend="oracle",
            pool=pool,
            oracle_version=oracle_version,
            vector_search=enable_vector_search,
        )
    except Exception:
        pool.close(force=True)
        raise


class ScopedMemory:
    """A small typed facade over ``OracleStore`` / ``InMemoryStore``.

    Namespace order is stable and tenant-first. This makes accidental cross-tenant
    reads visible in code review and gives every stored object an auditable type.
    """

    MEMORY_TYPES = {"working", "episodic", "semantic", "procedural", "evidence", "cache"}

    def __init__(self, store: Any, *, tenant_id: str) -> None:
        self.store = store
        self.tenant_id = tenant_id

    def namespace(self, application: str, memory_type: str, *scope: str) -> tuple[str, ...]:
        if memory_type not in self.MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {memory_type}")
        return (
            "advanced-harness",
            self.tenant_id,
            str(application),
            str(memory_type),
            *(str(item) for item in scope if str(item)),
        )

    def put(
        self,
        application: str,
        memory_type: str,
        value: Mapping[str, Any],
        *,
        key: str | None = None,
        scope: Iterable[str] = (),
    ) -> str:
        payload = json_safe(dict(value))
        payload.setdefault("memory_type", memory_type)
        payload.setdefault("created_at", utcnow())
        resolved_key = key or str(payload.get("id") or uuid.uuid4())
        payload.setdefault("id", resolved_key)
        self.store.put(
            self.namespace(application, memory_type, *scope),
            resolved_key,
            payload,
            index=None if memory_type in {"semantic", "cache"} else False,
        )
        return resolved_key

    def get(
        self,
        application: str,
        memory_type: str,
        key: str,
        *,
        scope: Iterable[str] = (),
    ) -> dict[str, Any] | None:
        item = self.store.get(
            self.namespace(application, memory_type, *scope), str(key)
        )
        return json_safe(item.value) if item is not None else None

    def search(
        self,
        application: str,
        memory_type: str,
        *,
        scope: Iterable[str] = (),
        limit: int = 100,
        filters: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        items = self.store.search(
            self.namespace(application, memory_type, *scope),
            filter=dict(filters or {}) or None,
            limit=max(1, min(int(limit), 1000)),
        )
        return [json_safe(item.value) for item in items]

    def semantic_search(
        self,
        application: str,
        memory_type: str,
        query: str,
        *,
        encoder: SemanticEncoder,
        scope: Iterable[str] = (),
        limit: int = 5,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        if getattr(self.store, "index_config", None):
            items = self.store.search(
                self.namespace(application, memory_type, *scope),
                query=query,
                limit=max(1, int(limit)),
            )
            results = []
            for item in items:
                score = float(item.score or 0.0)
                if score < threshold:
                    continue
                result = json_safe(item.value)
                result["similarity"] = round(score, 6)
                results.append(result)
            return results

        query_vector = encoder.embed(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for value in self.search(
            application, memory_type, scope=scope, limit=1000
        ):
            vector = value.get("embedding")
            if not isinstance(vector, list):
                continue
            score = encoder.cosine(query_vector, vector)
            if score >= threshold:
                result = dict(value)
                result["similarity"] = round(score, 6)
                scored.append((score, result))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
        return [value for _, value in scored[: max(1, int(limit))]]


__all__ = [
    "PersistenceResources",
    "ScopedMemory",
    "SemanticEncoder",
    "create_persistence",
    "json_safe",
    "stable_hash",
    "utcnow",
]
