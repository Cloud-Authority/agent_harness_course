"""Central configuration shared by the custom appbook, stages and notebook."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
COURSE_ROOT = APP_DIR.parents[2]
SHARED_DIR = COURSE_ROOT / "part_1" / "_shared"
FRONTEND_DIR = APP_DIR / "frontend"
DATA_DIR = APP_DIR / "data"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


for candidate in (COURSE_ROOT / ".env", APP_DIR / ".env"):
    _load_env(candidate)


@dataclass(frozen=True)
class Settings:
    mode: str = os.environ.get("ERPA_MODE", "local")
    memory_backend: str = os.environ.get("ERPA_MEMORY_BACKEND", "oamp")
    cache_enabled: bool = os.environ.get("ERPA_CACHE_ENABLED", "true").lower() == "true"
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
    anthropic_thinking: str = os.environ.get("ANTHROPIC_THINKING", "adaptive")
    e2b_api_key: str = os.environ.get("E2B_API_KEY", "")
    langsmith_api_key: str = os.environ.get("LANGSMITH_API_KEY", "")
    langsmith_project: str = os.environ.get("LANGSMITH_PROJECT", "erpa-custom-harness-appbook")
    tenant_id: str = os.environ.get("ERPA_TENANT_ID", "kata-workshop")
    user_id: str = os.environ.get("ERPA_USER_ID", "planner-01")
    agent_id: str = os.environ.get("ERPA_AGENT_ID", "erpa-merch-agent")
    ora_dsn: str = os.environ.get("ORA_DSN", "localhost:1521/FREEPDB1")
    ora_user: str = os.environ.get("ORA_AGENT_USER", "AGENT")
    ora_password: str = os.environ.get("ORA_AGENT_PWD", "")
    ora_wallet_location: str = os.environ.get("ORA_WALLET_LOCATION", "")
    ora_wallet_password: str = os.environ.get("ORA_WALLET_PASSWORD", "")
    ora_pool_min: int = int(os.environ.get("ORA_POOL_MIN", "1"))
    ora_pool_max: int = int(os.environ.get("ORA_POOL_MAX", "8"))
    ora_pool_increment: int = int(os.environ.get("ORA_POOL_INCREMENT", "1"))
    oamp_llm_model: str = os.environ.get("OAMP_LLM_MODEL", "anthropic/claude-opus-4-8")
    oamp_embed_backend: str = os.environ.get("OAMP_EMBED_BACKEND", "indb")
    oamp_indb_embed_model: str = os.environ.get("INDB_EMBED_MODEL", os.environ.get("OAMP_INDB_EMBED_MODEL", "ALL_MINILM_L12_V2"))
    oamp_indb_embed_input: str = os.environ.get("INDB_EMBED_INPUT", os.environ.get("OAMP_INDB_EMBED_INPUT", "DATA"))
    oamp_indb_embed_dimension: int = int(os.environ.get("INDB_EMBED_DIM", "384"))
    oamp_indb_embed_max_tokens: int = int(os.environ.get("INDB_EMBED_MAX_TOKENS", "512"))
    oamp_memory_store_id: str = os.environ.get("OAMP_MEMORY_STORE_ID", "ERPAMEM")
    oamp_default_ttl_days: int = int(os.environ.get("OAMP_DEFAULT_TTL_DAYS", "90"))
    oamp_max_ttl_days: int = int(os.environ.get("OAMP_MAX_TTL_DAYS", "365"))
    cache_table: str = os.environ.get("ERPA_CACHE_TABLE", "ERPA_SEMANTIC_CACHE")
    cache_namespace: str = os.environ.get("ERPA_CACHE_NAMESPACE", "erpa-prompt-v4")
    cache_score_threshold: float = float(os.environ.get("ERPA_CACHE_SCORE_THRESHOLD", "0.18"))
    cache_create_index: bool = os.environ.get("ERPA_CACHE_CREATE_INDEX", "false").lower() == "true"
    graph_max_iterations: int = int(os.environ.get("ERPA_GRAPH_MAX_ITERATIONS", "8"))
    graph_timeout_seconds: int = int(os.environ.get("ERPA_GRAPH_TIMEOUT_SECONDS", "180"))
    sandbox_output_limit: int = int(os.environ.get("ERPA_SANDBOX_OUTPUT_LIMIT", "3000"))
    prompt_cache_enabled: bool = False
    schedule_interval: int = int(os.environ.get("ERPA_SCHEDULE_INTERVAL_SECONDS", "0"))
    queue_poll_interval: int = int(os.environ.get("ERPA_QUEUE_POLL_SECONDS", "15"))

    @property
    def live(self) -> bool:
        return self.mode.lower() == "live"


settings = Settings()

if settings.langsmith_api_key:
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
