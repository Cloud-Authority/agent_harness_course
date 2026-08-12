"""Live Oracle stack used by the custom harness.

The application pool serves business tools, OAMP, OracleSemanticCache, OracleVS,
chat history and ScratchFS.  OracleSaver deliberately receives its own connection
so checkpoint transactions cannot leak into tool or memory transactions.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from backend.config import SHARED_DIR, settings

try:
    from langchain_core.embeddings import Embeddings as _LangChainEmbeddings
except ImportError:  # local teaching mode installs no LangChain packages
    class _LangChainEmbeddings:  # type: ignore[no-redef]
        pass

OAMP_EXTRACTION_INSTRUCTIONS = """
Extract durable merchandising knowledge only. Prefer explicit user preferences,
accepted/rejected commercial decisions, product or region facts, and reusable
operating guidelines. Preserve SKU, product line, size, location, region, PO and
date identifiers verbatim. Tag preferences separately from facts. Do not infer a
causal claim from correlation and do not store secrets, credentials, or raw PII.
""".strip()


@dataclass
class OracleStack:
    pool: Any
    checkpoint_connection: Any
    oamp: Any
    oamp_store: Any
    semantic_cache: Any
    checkpointer: Any
    embeddings: Any
    vector_store: Any
    history_factory: Any
    search_strategy: str


_stack: OracleStack | None = None
_lock = threading.RLock()


def _require_credentials() -> None:
    if not settings.ora_dsn or not settings.ora_user or not settings.ora_password:
        raise RuntimeError("ORA_DSN, ORA_AGENT_USER and ORA_AGENT_PWD are required in live mode")
    missing = [name for name, value in (
        ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
        ("E2B_API_KEY", settings.e2b_api_key),
        ("LANGSMITH_API_KEY", settings.langsmith_api_key),
    ) if not value]
    if missing:
        raise RuntimeError(f"Live mode requires {', '.join(missing)}")


class OracleInDatabaseEmbeddings(_LangChainEmbeddings):
    """LangChain Embeddings contract implemented with Oracle VECTOR_EMBEDDING."""

    def __init__(self, connection_pool: Any, model_name: str) -> None:
        self.pool = connection_pool
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        connection = self.pool.acquire()
        try:
            vectors: list[list[float]] = []
            with connection.cursor() as cursor:
                for text in texts:
                    cursor.execute(
                        f"SELECT VECTOR_EMBEDDING({self.model_name} USING :text AS DATA) FROM dual",
                        {"text": text},
                    )
                    vector = cursor.fetchone()[0]
                    vectors.append(list(vector.tolist()) if hasattr(vector, "tolist") else list(vector))
            return vectors
        finally:
            connection.close()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_pool() -> Any:
    """Create the shared python-oracledb thin-mode connection pool."""
    _require_credentials()
    import oracledb

    kwargs: dict[str, Any] = {
        "user": settings.ora_user,
        "password": settings.ora_password,
        "dsn": settings.ora_dsn,
        "min": settings.ora_pool_min,
        "max": settings.ora_pool_max,
        "increment": settings.ora_pool_increment,
    }
    if settings.ora_wallet_location:
        kwargs["wallet_location"] = settings.ora_wallet_location
    if settings.ora_wallet_password:
        kwargs["wallet_password"] = settings.ora_wallet_password
    return oracledb.create_pool(**kwargs)


def connect() -> Any:
    """Open a standalone thin-mode connection for diagnostics and scripts."""
    _require_credentials()
    import oracledb

    kwargs: dict[str, Any] = {
        "user": settings.ora_user,
        "password": settings.ora_password,
        "dsn": settings.ora_dsn,
    }
    if settings.ora_wallet_location:
        kwargs["wallet_location"] = settings.ora_wallet_location
    if settings.ora_wallet_password:
        kwargs["wallet_password"] = settings.ora_wallet_password
    return oracledb.connect(**kwargs)


def build_oamp(pool: Any) -> tuple[Any, Any, str]:
    """Build OAMP with the feature profile used by Oracle's support-assistant example."""
    from oracleagentmemory.core import (
        BackgroundExtractionQueueFullBehavior,
        MemoryExtractionConfig,
        MemoryExtractionMode,
        MemoryRetentionConfig,
        OracleAgentMemory,
        OracleDBMemoryStore,
        SchemaPolicy,
        SearchIndexSyncMode,
        SearchStrategy,
    )
    from oracleagentmemory.core.embedders import OracleDBEmbedder
    from oracleagentmemory.core.llms import Llm

    memory_llm = Llm(
        model=settings.oamp_llm_model,
        reasoning_effort="high",
        max_tokens=4096,
    )
    backend = settings.oamp_embed_backend.lower()
    if backend not in {"indb", "oracledb"}:
        raise ValueError("The complete harness requires OAMP_EMBED_BACKEND=indb")
    embedder = OracleDBEmbedder(
        connection=pool,
        model=settings.oamp_indb_embed_model,
        input_name=settings.oamp_indb_embed_input,
        embedding_dimension=settings.oamp_indb_embed_dimension,
        max_input_tokens=settings.oamp_indb_embed_max_tokens,
        normalize=True,
        batch_size=16,
    )
    search_strategy = SearchStrategy.HYBRID
    search_index_sync = SearchIndexSyncMode.ON_COMMIT

    retention = MemoryRetentionConfig(
        default_ttl_days=settings.oamp_default_ttl_days,
        max_ttl_days=settings.oamp_max_ttl_days,
    )
    extraction = MemoryExtractionConfig(
        extraction_mode=MemoryExtractionMode.BACKGROUND,
        background_extraction_queue_full_behavior=BackgroundExtractionQueueFullBehavior.WAIT_THEN_RAISE,
        background_extraction_queue_put_timeout_seconds=10,
        extract_memories=True,
        memory_extraction_frequency=1,
        memory_extraction_window=-1,
        memory_extraction_token_limit=6000,
        enable_context_summary=True,
        context_summary_update_frequency=2,
        memory_extraction_custom_instructions=OAMP_EXTRACTION_INSTRUCTIONS,
        memory_extraction_inherit_message_metadata=(
            "tenant_id", "workflow_id", "channel", "tags", "approval_state", "source",
        ),
    )
    store_kwargs: dict[str, Any] = {
        "embedder": embedder,
        "pool": pool,
        "schema_policy": SchemaPolicy.CREATE_IF_NECESSARY,
        "memory_store_id": settings.oamp_memory_store_id,
        "search_strategy": search_strategy,
        "memory_retention_config": retention,
    }
    store_kwargs["search_index_sync"] = search_index_sync
    memory_store = OracleDBMemoryStore(**store_kwargs)
    memory = OracleAgentMemory(
        store=memory_store,
        llm=memory_llm,
        memory_extraction_config=extraction,
    )
    return memory, memory_store, search_strategy.value


def build_langchain_components(pool: Any) -> dict[str, Any]:
    """Build the current Oracle integrations used by the live request path."""
    from langchain_oracledb import OracleChatMessageHistory, OracleSemanticCache
    from langchain_oracledb.vectorstores import DistanceStrategy, OracleVS

    embeddings = OracleInDatabaseEmbeddings(pool, settings.oamp_indb_embed_model)
    semantic_cache = OracleSemanticCache(
        client=pool,
        embedding=embeddings,
        table_name=settings.cache_table,
        distance_strategy=DistanceStrategy.COSINE,
        create_index_if_missing=settings.cache_create_index,
        score_threshold=settings.cache_score_threshold,
    )
    vector_store = OracleVS(
        client=pool,
        embedding_function=embeddings,
        table_name="ERPA_DOCS",
        distance_strategy=DistanceStrategy.COSINE,
    )

    def history(session_id: str) -> Any:
        return OracleChatMessageHistory(
            session_id=session_id,
            client=pool,
            table_name="ERPA_CHAT_HISTORY",
        )

    return {
        "embeddings": embeddings,
        "semantic_cache": semantic_cache,
        "vector_store": vector_store,
        "history_factory": history,
    }


def seed_vector_store(pool: Any, vector_store: Any) -> None:
    """Embed the shared institutional corpus once; duplicate startup is a no-op."""
    connection = pool.acquire()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ERPA_DOCS")
            if int(cursor.fetchone()[0]) > 0:
                return
    finally:
        connection.close()

    from langchain_core.documents import Document

    documents, ids = [], []
    for path in sorted((SHARED_DIR / "fixtures" / "notion_pages").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        documents.append(Document(
            page_content=text,
            metadata={
                "source": "notion_fixture",
                "page": path.name,
                "title": text.splitlines()[0].lstrip("# "),
            },
        ))
        ids.append(f"erpa-doc-{path.stem}")
    vector_store.add_documents(documents, ids=ids)


def build_checkpointer(connection: Any) -> Any:
    """Create and initialise OracleSaver on its dedicated connection."""
    from langgraph_oracledb.checkpoint.oracle import OracleSaver

    checkpointer = OracleSaver(connection, json_size_threshold_mb=0.0)
    checkpointer.setup()
    return checkpointer


def get_oracle_stack() -> OracleStack:
    """Lazily initialise the shared live stack exactly once per process."""
    global _stack
    if not settings.live:
        raise RuntimeError("Oracle stack is available only when ERPA_MODE=live")
    with _lock:
        if _stack is None:
            pool = create_pool()
            checkpoint_connection = connect()
            try:
                oamp, oamp_store, strategy = build_oamp(pool)
                langchain = build_langchain_components(pool)
                seed_vector_store(pool, langchain["vector_store"])
                _stack = OracleStack(
                    pool=pool,
                    checkpoint_connection=checkpoint_connection,
                    oamp=oamp,
                    oamp_store=oamp_store,
                    semantic_cache=langchain["semantic_cache"],
                    checkpointer=build_checkpointer(checkpoint_connection),
                    embeddings=langchain["embeddings"],
                    vector_store=langchain["vector_store"],
                    history_factory=langchain["history_factory"],
                    search_strategy=strategy,
                )
            except Exception:
                checkpoint_connection.close()
                pool.close(force=True)
                raise
    return _stack


def close_oracle_stack() -> None:
    """Flush background extraction, then close the common Oracle pool."""
    global _stack
    with _lock:
        if _stack is None:
            return
        try:
            _stack.oamp.close(timeout=120)
        finally:
            _stack.checkpoint_connection.close()
            _stack.pool.close(force=True)
            _stack = None


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "source checkout"


def preflight(*, initialise: bool = True) -> dict[str, Any]:
    """Report the live database and concrete adapter implementations."""
    _require_credentials()
    stack = get_oracle_stack() if initialise else None
    connection = stack.pool.acquire() if stack else connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT SYS_CONTEXT('USERENV','DB_NAME') FROM dual")
            database = cursor.fetchone()[0]
            cursor.execute(
                "SELECT product,version_full FROM product_component_version "
                "WHERE product LIKE 'Oracle%Database%' FETCH FIRST 1 ROW ONLY"
            )
            product, database_version = cursor.fetchone()
            business_tables = {}
            for table in ("PRODUCTS", "VARIANTS", "CUSTOMERS", "ORDERS", "ORDER_LINES", "INVENTORY"):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                business_tables[table.lower()] = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT table_name FROM user_tables "
                "WHERE table_name LIKE 'ERPA%' OR table_name LIKE 'CHECKPOINT%' "
                "ORDER BY table_name"
            )
            harness_tables = [row[0] for row in cursor.fetchall()]
        return {
            "ready": True,
            "mode": "live",
            "database": database,
            "database_banner": f"{product} {database_version}",
            "thin_mode": True,
            "substrate": "Oracle AI Database 26ai Free (Docker Compose) or a compatible managed Oracle AI Database",
            "business_tables": business_tables,
            "harness_tables": harness_tables,
            "components": {
                "agent_memory": type(stack.oamp).__name__ if stack else "OracleAgentMemory",
                "semantic_cache": type(stack.semantic_cache).__name__ if stack else "OracleSemanticCache",
                "checkpointer": type(stack.checkpointer).__name__ if stack else "OracleSaver",
                "chat_history": "OracleChatMessageHistory",
                "vector_store": type(stack.vector_store).__name__ if stack else "OracleVS",
                "embeddings": type(stack.embeddings).__name__ if stack else "OracleInDatabaseEmbeddings",
                "model": f"ChatAnthropic({settings.anthropic_model}, thinking={settings.anthropic_thinking})",
                "scratch": "Oracle SecureFile ScratchFS + session-end promotion trigger",
                "sandbox": "E2B Code Interpreter",
                "tracing": f"LangSmith project {settings.langsmith_project}",
            },
            "versions": {
                "oracleagentmemory": _package_version("oracleagentmemory"),
                "langchain-oracledb": _package_version("langchain-oracledb"),
                "langgraph-oracledb": _package_version("langgraph-oracledb"),
            },
            "oamp_features": [
                "background memory extraction",
                "custom extraction instructions",
                "context cards and summaries",
                "metadata inheritance and filtering",
                "exact scope matching",
                "typed manual memories",
                "TTL retention, update and deletion APIs",
                f"{stack.search_strategy if stack else 'vector/hybrid'} search",
            ],
        }
    finally:
        if stack:
            connection.close()
        else:
            connection.close()
