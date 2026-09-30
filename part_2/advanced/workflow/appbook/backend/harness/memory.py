"""Traveller memory on Oracle Agent Memory: what this person prefers when they travel."""
from __future__ import annotations

import hashlib
import re

from oracleagentmemory.core import (MemoryExtractionConfig, MemoryExtractionMode, OracleAgentMemory,
                                    OracleDBMemoryStore, SchemaPolicy, SearchIndexSyncMode, SearchStrategy)
from oracleagentmemory.core.embedders import OracleDBEmbedder
from oracleagentmemory.core.llms import Llm

from shared.oracle import ORA
from shared.oracle import pool

from .config import CFG

_memory: dict[str, object] = {}


def agent_memory() -> OracleAgentMemory:
    """One store for every traveller, scoped by user and agent. Built on first use."""
    if "oamp" not in _memory:
        embedder = OracleDBEmbedder(connection=pool("memory", max=8), model=ORA.embed_model, input_name="DATA",
                                    embedding_dimension=384, normalize=True, batch_size=16)
        store = OracleDBMemoryStore(
            embedder=embedder, pool=pool("memory", max=8), schema_policy=SchemaPolicy.CREATE_IF_NECESSARY,
            memory_store_id=CFG.memory_store_id, search_strategy=SearchStrategy.HYBRID,
            search_index_sync=SearchIndexSyncMode.ON_COMMIT)
        extraction = MemoryExtractionConfig(extraction_mode=MemoryExtractionMode.BACKGROUND,
                                            extract_memories=False)     # this harness writes memories itself
        _memory["store"] = store
        _memory["oamp"] = OracleAgentMemory(store=store, llm=Llm(model=f"anthropic/{CFG.model}", max_tokens=2000),
                                            memory_extraction_config=extraction)
        if store.get("agent_profile", CFG.agent_id) is None:
            _memory["oamp"].add_agent(CFG.agent_id, "Trip-booking workflow", metadata={"tenant_id": CFG.tenant_id})
    return _memory["oamp"]


def ensure_traveller(traveller_id: str, description: str = "A traveller") -> None:
    oamp = agent_memory()
    if _memory["store"].get("user_profile", traveller_id) is None:
        oamp.add_user(traveller_id, description, metadata={"tenant_id": CFG.tenant_id})


def memory_key(content: str) -> str:
    return "mem-" + hashlib.sha256(re.sub(r"\s+", " ", content).strip().lower().encode()).hexdigest()[:24]


def remember(traveller_id: str, content: str, kind: str = "preference", source: str = "explicit") -> dict:
    """Store one statement about the traveller, once."""
    ensure_traveller(traveller_id)
    key = memory_key(content)
    if _memory["store"].get(kind, key) is not None:
        return {"memory_id": key, "stored": False}
    agent_memory().add_memory(content, memory_type=kind, memory_id=key, user_id=traveller_id,
                              agent_id=CFG.agent_id, ttl_days=365,
                              metadata={"tenant_id": CFG.tenant_id, "source": source})
    return {"memory_id": key, "stored": True}


def recall(traveller_id: str, query: str, limit: int = 6) -> list[str]:
    """What is known about this traveller that bears on the request."""
    ensure_traveller(traveller_id)
    found = agent_memory().search(query, user_id=traveller_id, agent_id=CFG.agent_id, exact_user_match=True,
                                  exact_agent_match=True, exact_thread_match=False, max_results=limit,
                                  record_types=["preference", "fact", "guideline"],
                                  metadata_filter={"tenant_id": CFG.tenant_id})
    return [getattr(getattr(item, "record", item), "content", "") for item in found]


def forget_traveller(traveller_id: str) -> None:
    ensure_traveller(traveller_id)
    agent_memory().delete_user(traveller_id, cascade=True)
