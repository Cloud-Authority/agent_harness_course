"""Memory provider factory and scoped helpers.

A memory provider is the storage layer behind MemoRizz: it holds each memory
type (conversation, knowledge base, entity, workflow, skills, tool log) and
answers scoped searches. This track uses the filesystem provider, which stores
JSON documents under ``data/memory`` and searches vectors with FAISS.

An embedding turns text into a vector so that a search can match meaning
rather than exact words. Anthropic offers no embeddings endpoint, so this
track embeds with a small local model served by Ollama. If no embedding model
is available, recall still works by keyword, with lower quality.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import paths
from .settings import Settings

# Conversation, facts and skills are scoped by memory_id and user_id. These are
# the stores a reset clears for one workshop scope.
SCOPED_TYPES = ("conversation_memory", "knowledge_base", "entity_memory", "workflow_memory",
                "summaries", "semantic_cache", "short_term_memory", "tool_log", "shared_memory")
LONG_TERM_KINDS = ("preference", "fact", "guideline")


def _normalise_url(value: str) -> str:
    text = str(value or "").strip()
    return text if "://" in text else f"http://{text}"


def embedding_status(settings: Settings) -> Dict[str, Any]:
    """Check the embedding model without raising. Returns what recall will use."""
    if settings.embedding_provider != "ollama":
        return {"provider": settings.embedding_provider, "ready": bool(settings.embedding_provider),
                "model": settings.embedding_model, "mode": "provider-managed"}
    try:
        import ollama

        client = ollama.Client(host=_normalise_url(settings.ollama_url), timeout=10)
        vector = client.embeddings(model=settings.embedding_model, prompt="ready")
        size = len(getattr(vector, "embedding", None) or vector["embedding"])
        return {"provider": "ollama", "model": settings.embedding_model, "ready": size > 0,
                "dimensions": size, "mode": "semantic recall"}
    except Exception as exc:
        return {"provider": "ollama", "model": settings.embedding_model, "ready": False,
                "mode": "keyword recall", "reason": type(exc).__name__}


def make_memory_provider(settings: Settings) -> Any:
    """Build the memory provider named by ``PPA_MEMORY_BACKEND``.

    ``filesystem`` (the default) needs nothing but a folder. ``oracle`` reads
    ``ORACLE_USER``, ``ORACLE_PASSWORD`` and ``ORACLE_DSN`` and uses Oracle AI
    Database for storage and vector search.
    """
    embedding_config = None
    if settings.embedding_provider == "ollama":
        embedding_config = {"model": settings.embedding_model,
                            "base_url": _normalise_url(settings.ollama_url)}
    if settings.embedding_provider and embedding_status(settings)["ready"]:
        from memorizz.embeddings import configure_embeddings

        # Personas, skills and the tool router call the global embedder, so it
        # must point at the same model as the provider.
        configure_embeddings(settings.embedding_provider, embedding_config or {})
    else:
        embedding_config = None

    if settings.memory_backend == "oracle":
        from memorizz import OracleProvider

        in_database = os.environ.get("MEMORIZZ_ORACLE_IN_DATABASE_EMBEDDING", "true").lower()
        return OracleProvider.from_env(
            provision_if_missing=False,
            index_policy=os.environ.get("MEMORIZZ_ORACLE_INDEX_POLICY", "lazy"),
            **({} if in_database in {"1", "true", "yes"} else {
                "in_database_embedding": False,
                "embedding_provider": settings.embedding_provider,
                "embedding_config": embedding_config}),
        )
    if settings.memory_backend != "filesystem":
        raise ValueError("PPA_MEMORY_BACKEND must be filesystem or oracle")

    from memorizz.memory_provider import FileSystemConfig, FileSystemProvider

    return FileSystemProvider(FileSystemConfig(
        root_path=paths.memory_root(),
        embedding_provider=settings.embedding_provider if embedding_config else None,
        embedding_config=embedding_config,
    ))


def _memory_type(name: str):
    from memorizz.enums.memory_type import MemoryType

    return MemoryType(name)


def reset_scope(provider: Any, *, memory_id: str, user_id: str,
                agent_names: Optional[List[str]] = None) -> Dict[str, int]:
    """Delete only this workshop's rows, so a rerun starts from a clean baseline.

    Oracle has ``delete_scope``. The filesystem provider does not, so rows are
    matched one store at a time. Rows of other memory IDs and users are kept.
    """
    removed: Dict[str, int] = {}
    agent_ids = set()
    for agent in provider.list_memagents() or []:
        name = getattr(agent, "name", None) or (agent.get("name") if isinstance(agent, dict) else None)
        if agent_names and name in agent_names:
            agent_ids.add(str(getattr(agent, "agent_id", None) or agent.get("agent_id")))
    delete_scope = getattr(provider, "delete_scope", None)
    if callable(delete_scope):
        delete_scope(memory_id=memory_id)
        delete_scope(user_id=user_id)
        if agent_ids:
            delete_scope(agent_ids=sorted(agent_ids))
        return {"delete_scope": 1}
    for name in (*SCOPED_TYPES, "toolbox", "skillbox", "personas"):
        try:
            memory_type = _memory_type(name)
            rows = provider.list_all(memory_type) or []
        except Exception:
            continue
        for row in rows:
            owned = (row.get("memory_id") == memory_id or row.get("user_id") == user_id
                     or str(row.get("agent_id")) in agent_ids)
            record_id = row.get("_id") or row.get("id")
            if owned and record_id and provider.delete_by_id(str(record_id), memory_type):
                removed[name] = removed.get(name, 0) + 1
    for agent_id in agent_ids:
        if provider.delete_memagent(agent_id):
            removed["memagent"] = removed.get("memagent", 0) + 1
    return removed


def remember(provider: Any, statement: str, *, category: str, memory_id: str, user_id: str,
             source: str = "owner_statement") -> str:
    """Write one durable memory to the knowledge base, with an embedding when possible."""
    if provider is None:
        raise RuntimeError("No memory provider is attached to the runtime.")
    if category not in LONG_TERM_KINDS:
        raise ValueError(f"category must be one of {LONG_TERM_KINDS}")
    record = {"memory_id": memory_id, "user_id": user_id, "content": statement.strip(),
              "memory_type": category, "importance": 0.9,
              "metadata": {"source": source, "kind": category}}
    try:
        record["embedding"] = provider.embed_text(record["content"])
    except Exception:
        pass  # keyword recall still finds the row
    return str(provider.store(record, memory_store_type=_memory_type("knowledge_base")))


def long_term_memories(provider: Any, *, memory_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Durable memories for one scope, without vectors, oldest first."""
    rows = provider.list_all(_memory_type("knowledge_base")) or []
    chosen = [row for row in rows
              if row.get("memory_id") == memory_id and row.get("user_id") == user_id]
    chosen.sort(key=lambda row: str(row.get("timestamp") or ""))
    return [{"record_id": row.get("_id") or row.get("id"), "kind": row.get("memory_type"),
             "content": row.get("content"), "embedded": bool(row.get("embedding")),
             "stored_at": row.get("timestamp")} for row in chosen]


def store_counts(provider: Any, *, memory_id: str, user_id: str) -> Dict[str, int]:
    """How many rows each memory store holds for this scope."""
    counts = {}
    for name in SCOPED_TYPES:
        try:
            rows = provider.list_all(_memory_type(name)) or []
        except Exception:
            continue
        counts[name] = sum(1 for row in rows if row.get("memory_id") == memory_id
                           or row.get("user_id") == user_id)
    return counts
