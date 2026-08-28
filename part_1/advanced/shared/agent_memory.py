"""Oracle Agent Memory adapter used by the durable workflow harness.

The workflow deliberately keeps three kinds of persistence separate:

* ``OracleSaver`` owns the LangGraph recovery cursor and thread-local state.
* ``OracleAgentMemory`` owns governed facts, guidelines, thread messages, and
  episodic memories.
* ``OracleStore`` is used only as an exactly-once operation/audit ledger.

That separation is more important than the fact that all three can share one
Oracle database.  It keeps memory retrieval, control-flow recovery, and external
side-effect reconciliation from becoming one ambiguous abstraction.
"""

from __future__ import annotations

import json
import threading
from importlib.metadata import version
from typing import Any, Mapping

from .config import AdvancedSettings, settings as default_settings
from .persistence import json_safe


AGENT_ID = "supplier-compliance-harness"
PROCEDURAL_ID = "skillbox-routing-guideline-v1"
LEGACY_PROCEDURAL_ID = "supplier-compliance-sop-v4"
SEMANTIC_ID = "supplier-compliance-rules-v1"


def _memory_content(payload: Mapping[str, Any]) -> str:
    """Return searchable prose while retaining the structured payload in metadata."""

    return "\n".join(
        str(payload.get(field) or "")
        for field in ("title", "text", "version")
        if payload.get(field)
    )


class InMemoryAgentMemoryManager:
    """Deterministic, explicitly non-durable mirror used by tests and offline labs."""

    backend = "memory (non-durable teaching fallback)"
    search_strategy = "lexical"

    def __init__(
        self, course_settings: AdvancedSettings = default_settings
    ) -> None:
        self.settings = course_settings
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._messages: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def seed_governance(
        self,
        *,
        procedural: Mapping[str, Any],
        semantic: Mapping[str, Any],
    ) -> None:
        with self._lock:
            self._records[("guideline", PROCEDURAL_ID)] = json_safe(procedural)
            self._records.pop(("guideline", LEGACY_PROCEDURAL_ID), None)
            self._records[("fact", SEMANTIC_ID)] = json_safe(semantic)

    def recall_context(self, thread_id: str, objective: str) -> dict[str, Any]:
        with self._lock:
            messages = self._messages.setdefault(thread_id, [])
            if not messages:
                messages.append({"role": "user", "content": objective})
            procedural = json_safe(
                self._records[("guideline", PROCEDURAL_ID)]
            )
            semantic = json_safe(self._records[("fact", SEMANTIC_ID)])
        return {
            "procedural": procedural,
            "semantic": semantic,
            "context_card": (
                "<memory_context>\n"
                f"<guideline>{procedural['text']}</guideline>\n"
                f"<fact>{semantic['text']}</fact>\n"
                f"<current_objective>{objective}</current_objective>\n"
                "</memory_context>"
            ),
        }

    def record_event(self, event: Mapping[str, Any]) -> None:
        value = json_safe(dict(event))
        with self._lock:
            self._events.setdefault(str(value["thread_id"]), []).append(value)

    def events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._events.get(thread_id, []))
        return sorted(json_safe(values), key=lambda item: item["timestamp"])

    def record_outcome(
        self, thread_id: str, report: Mapping[str, Any], publication: Mapping[str, Any]
    ) -> None:
        with self._lock:
            self._records[("fact", f"outcome-{report['report_id']}")] = {
                "thread_id": thread_id,
                "report": json_safe(report),
                "publication": json_safe(publication),
            }

    def status(self) -> dict[str, Any]:
        return {
            "provider": type(self).__name__,
            "implementation": "OAMP-shaped in-memory teaching adapter",
            "substrate": self.backend,
            "search_strategy": self.search_strategy,
            "record_types": {
                "procedural": "guideline",
                "semantic": "fact",
                "episodic": "memory",
                "conversation": "thread messages",
            },
            "embedding": {
                "active": False,
                "provider": "none",
                "model": "none",
                "reason": "offline lexical fallback",
            },
            "automatic_extraction": {
                "active": False,
                "model_provider": "none",
                "reason": "the workflow writes typed memories explicitly",
            },
        }

    def close(self) -> None:
        return None


class OracleAgentMemoryManager:
    """Thin course adapter over the published Oracle Agent Memory 26.6 package."""

    backend = "oracle"

    def __init__(
        self,
        pool: Any,
        course_settings: AdvancedSettings = default_settings,
    ) -> None:
        from oracleagentmemory.core import (
            MemoryExtractionConfig,
            OracleAgentMemory,
            OracleDBMemoryStore,
            SchemaPolicy,
            SearchIndexSyncMode,
            SearchStrategy,
        )

        self.settings = course_settings
        self._lock = threading.RLock()
        strategy_name = course_settings.agent_memory_search_strategy
        try:
            strategy = SearchStrategy(strategy_name)
        except ValueError as exc:
            raise ValueError(
                "ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY must be keyword, vector, or hybrid"
            ) from exc

        embedder = None
        if strategy in {SearchStrategy.VECTOR, SearchStrategy.HYBRID}:
            if not course_settings.openai_api_key:
                raise RuntimeError(
                    f"Oracle Agent Memory {strategy.value} search requires a valid "
                    "OPENAI_API_KEY for the configured embedding route"
                )
            from oracleagentmemory.core.embedders import Embedder

            embedder = Embedder(
                model=f"openai/{course_settings.openai_embed_model}",
                api_key=course_settings.openai_api_key,
                embedding_dimension=course_settings.embedding_dimensions,
                max_input_tokens=course_settings.agent_memory_embed_max_tokens,
            )

        store_options: dict[str, Any] = {
            "embedder": embedder,
            "pool": pool,
            "memory_store_id": course_settings.agent_memory_store_id,
            "search_strategy": strategy,
        }
        if strategy in {SearchStrategy.KEYWORD, SearchStrategy.HYBRID}:
            store_options["search_index_sync"] = SearchIndexSyncMode.ON_COMMIT
        try:
            # The normal restart path is read/operate only and therefore does not
            # retry optional schema housekeeping DDL on every process start.
            self.store = OracleDBMemoryStore(
                **store_options, schema_policy=SchemaPolicy.REQUIRE_EXISTING
            )
        except Exception:
            # A genuinely fresh installation gets the documented managed-schema
            # bootstrap. Optional retention scheduling may require a DBA-granted
            # CREATE JOB privilege; memory records remain usable without that job.
            self.store = OracleDBMemoryStore(
                **store_options, schema_policy=SchemaPolicy.CREATE_IF_NECESSARY
            )
        self.client = OracleAgentMemory(
            store=self.store,
            memory_extraction_config=MemoryExtractionConfig(
                extract_memories=False,
                enable_context_summary=False,
            ),
        )
        self.search_strategy = strategy.value

    @property
    def _metadata(self) -> dict[str, Any]:
        return {
            "tenant_id": self.settings.tenant_id,
            "application": "workflow",
        }

    def _add_once(
        self,
        record_type: str,
        record_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        if self.store.get(record_type, record_id) is not None:
            return
        try:
            self.client.add_memory(
                _memory_content(payload),
                memory_type=record_type,
                memory_id=record_id,
                user_id=None,
                agent_id=AGENT_ID,
                metadata={
                    **self._metadata,
                    "course_memory_type": (
                        "procedural" if record_type == "guideline" else "semantic"
                    ),
                    "payload": json_safe(dict(payload)),
                },
            )
        except Exception:
            # A second process may win the seed race between get() and add(). Only
            # suppress the error when the exact durable record now exists.
            if self.store.get(record_type, record_id) is None:
                raise

    def seed_governance(
        self,
        *,
        procedural: Mapping[str, Any],
        semantic: Mapping[str, Any],
    ) -> None:
        with self._lock:
            self._add_once("guideline", PROCEDURAL_ID, procedural)
            self._add_once("fact", SEMANTIC_ID, semantic)
            if self.store.get("guideline", LEGACY_PROCEDURAL_ID) is not None:
                self.store.delete("guideline", LEGACY_PROCEDURAL_ID)

    def _thread(self, thread_id: str, objective: str = "") -> Any:
        from oracleagentmemory.apis import Message

        try:
            thread = self.client.get_thread(thread_id)
        except KeyError:
            thread = self.client.create_thread(
                thread_id=thread_id,
                user_id=self.settings.user_id,
                agent_id=AGENT_ID,
                metadata={**self._metadata, "case_id": "SUP-1042:2026-Q3"},
                context_card_token_limit=3000,
            )
        if objective and not thread.get_messages():
            thread.add_messages(
                [
                    Message(
                        role="user",
                        content=objective,
                        metadata={**self._metadata, "kind": "workflow_objective"},
                    )
                ]
            )
        return thread

    @staticmethod
    def _payload(record: Any) -> dict[str, Any]:
        metadata = dict(getattr(record, "metadata", None) or {})
        payload = metadata.get("payload")
        return json_safe(payload if isinstance(payload, Mapping) else {})

    def recall_context(self, thread_id: str, objective: str) -> dict[str, Any]:
        with self._lock:
            thread = self._thread(thread_id, objective)
            procedural_record = self.store.get("guideline", PROCEDURAL_ID)
            semantic_record = self.store.get("fact", SEMANTIC_ID)
            if procedural_record is None or semantic_record is None:
                raise RuntimeError("Oracle Agent Memory governance seed is incomplete")
            card = thread.get_context_card(
                fallback_message_count=4,
                max_relevant_results=6,
                max_recent_messages=3,
                min_relevant_results_by_type={"guideline": 1, "fact": 1},
            )
            return {
                "procedural": self._payload(procedural_record),
                "semantic": self._payload(semantic_record),
                "context_card": card.content,
            }

    def record_event(self, event: Mapping[str, Any]) -> None:
        value = json_safe(dict(event))
        with self._lock:
            self.client.add_memory(
                json.dumps(value, sort_keys=True, ensure_ascii=False),
                memory_type="memory",
                memory_id=str(value["event_id"]),
                user_id=self.settings.user_id,
                agent_id=AGENT_ID,
                thread_id=str(value["thread_id"]),
                metadata={
                    **self._metadata,
                    "course_memory_type": "episodic",
                    "kind": "workflow_event",
                    "event": value,
                },
            )

    def events(self, thread_id: str) -> list[dict[str, Any]]:
        records = self.store.list(
            "memory",
            limit=500,
            thread_id=thread_id,
            user_id=self.settings.user_id,
            agent_id=AGENT_ID,
            metadata_filter={
                "tenant_id": self.settings.tenant_id,
                "kind": "workflow_event",
            },
        )
        events = []
        for record in records:
            metadata = dict(getattr(record, "metadata", None) or {})
            event = metadata.get("event")
            if isinstance(event, Mapping):
                events.append(json_safe(dict(event)))
        return sorted(events, key=lambda item: item["timestamp"])

    def record_outcome(
        self, thread_id: str, report: Mapping[str, Any], publication: Mapping[str, Any]
    ) -> None:
        memory_id = f"outcome-{report['report_id']}"
        if self.store.get("fact", memory_id) is not None:
            return
        self.client.add_memory(
            (
                f"Published supplier compliance outcome {report['report_id']}: "
                f"{report['recommendation']}"
            ),
            memory_type="fact",
            memory_id=memory_id,
            user_id=self.settings.user_id,
            agent_id=AGENT_ID,
            thread_id=thread_id,
            metadata={
                **self._metadata,
                "course_memory_type": "semantic",
                "kind": "published_outcome",
                "report": json_safe(report),
                "publication": json_safe(publication),
            },
        )

    def status(self) -> dict[str, Any]:
        embedding_active = self.search_strategy in {"vector", "hybrid"}
        return {
            "provider": type(self.client).__name__,
            "implementation": "oracleagentmemory.OracleAgentMemory",
            "version": version("oracleagentmemory"),
            "substrate": type(self.store).__name__,
            "memory_store_id": self.settings.agent_memory_store_id,
            "search_strategy": self.search_strategy,
            "record_types": {
                "procedural": "guideline",
                "semantic": "fact",
                "episodic": "memory",
                "conversation": "thread messages",
            },
            "embedding": {
                "active": embedding_active,
                "provider": "OpenAI via LiteLLM" if embedding_active else "none",
                "model": (
                    self.settings.openai_embed_model if embedding_active else "none"
                ),
                "dimensions": (
                    self.settings.embedding_dimensions if embedding_active else None
                ),
                "configured_option": {
                    "provider": "OpenAI via LiteLLM",
                    "model": self.settings.openai_embed_model,
                    "dimensions": self.settings.embedding_dimensions,
                    "activate_with": (
                        "ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY=vector and a valid "
                        "OPENAI_API_KEY"
                    ),
                },
                "reason": (
                    None
                    if embedding_active
                    else "explicit keyword fallback; the default profile uses vector search"
                ),
            },
            "automatic_extraction": {
                "active": False,
                "model_provider": "none",
                "reason": "typed workflow memories are written explicitly and deterministically",
            },
        }

    def close(self) -> None:
        self.client.close(timeout=30)


def create_agent_memory_manager(
    course_settings: AdvancedSettings,
    *,
    pool: Any = None,
) -> InMemoryAgentMemoryManager | OracleAgentMemoryManager:
    if course_settings.backend == "memory":
        return InMemoryAgentMemoryManager(course_settings)
    if course_settings.backend == "oracle":
        if pool is None:
            raise RuntimeError("Oracle Agent Memory requires the shared Oracle pool")
        return OracleAgentMemoryManager(pool, course_settings)
    raise ValueError("ADVANCED_BACKEND must be oracle or memory")


__all__ = [
    "AGENT_ID",
    "InMemoryAgentMemoryManager",
    "OracleAgentMemoryManager",
    "create_agent_memory_manager",
]
