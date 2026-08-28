"""Configuration for the advanced course sections.

The advanced material deliberately uses the same root ``.env`` as Part 1.  Values
prefixed with ``ADVANCED_`` win; the existing ``ORA_*`` and model variables remain
valid so an instructor can reuse the already provisioned local Oracle service.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ADVANCED_DIR = Path(__file__).resolve().parents[1]
PART_1_DIR = ADVANCED_DIR.parent
COURSE_ROOT = PART_1_DIR.parent
DATA_DIR = ADVANCED_DIR / ".data"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


for _candidate in (COURSE_ROOT / ".env", ADVANCED_DIR / ".env"):
    _load_env(_candidate)

# Advanced examples are self-auditing in Oracle. Do not inherit Part 1's remote
# tracing switch accidentally; instructors can opt in explicitly for this module.
if os.environ.get("ADVANCED_LANGSMITH_TRACING", "false").strip().lower() not in {
    "1",
    "true",
    "yes",
    "on",
}:
    os.environ["LANGSMITH_TRACING"] = "false"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def usable_runtime_secret(value: str) -> bool:
    """Reject empty values and obvious documentation placeholders."""

    normalized = str(value or "").strip()
    return (
        len(normalized) >= 20
        and "replace" not in normalized.lower()
        and "<runtime" not in normalized.lower()
    )


@dataclass(frozen=True)
class AdvancedSettings:
    """Secret-free settings facade.

    ``backend=oracle`` is the course path. ``memory`` exists only for unit tests
    and for reading a populated notebook when Oracle is temporarily unavailable;
    every UI status response labels that fallback explicitly.
    """

    backend: str = os.environ.get("ADVANCED_BACKEND", "oracle").strip().lower()
    ora_dsn: str = os.environ.get(
        "ADVANCED_ORA_DSN", os.environ.get("ORA_DSN", "127.0.0.1:1521/FREEPDB1")
    )
    ora_user: str = os.environ.get(
        "ADVANCED_ORA_USER", os.environ.get("ORA_AGENT_USER", "AGENT")
    )
    ora_password: str = os.environ.get(
        "ADVANCED_ORA_PASSWORD", os.environ.get("ORA_AGENT_PWD", "")
    )
    ora_wallet_location: str = os.environ.get(
        "ADVANCED_ORA_WALLET_LOCATION", os.environ.get("ORA_WALLET_LOCATION", "")
    )
    ora_wallet_password: str = os.environ.get(
        "ADVANCED_ORA_WALLET_PASSWORD", os.environ.get("ORA_WALLET_PASSWORD", "")
    )
    ora_pool_min: int = int(os.environ.get("ADVANCED_ORA_POOL_MIN", "1"))
    ora_pool_max: int = int(os.environ.get("ADVANCED_ORA_POOL_MAX", "8"))
    tenant_id: str = os.environ.get("ADVANCED_TENANT_ID", "oreilly-advanced")
    user_id: str = os.environ.get("ADVANCED_USER_ID", "course-operator")

    tavily_api_key: str = os.environ.get("TAVILY_API_KEY", "")
    tavily_search_depth: str = os.environ.get(
        "ADVANCED_TAVILY_SEARCH_DEPTH", "advanced"
    )
    tavily_results_per_worker: int = int(
        os.environ.get("ADVANCED_TAVILY_RESULTS_PER_WORKER", "5")
    )
    research_source: str = os.environ.get(
        "ADVANCED_RESEARCH_SOURCE", "tavily"
    ).strip().lower()

    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get(
        "ADVANCED_OPENAI_MODEL", "gpt-5.5"
    )
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.environ.get(
        "ADVANCED_ANTHROPIC_MODEL", "claude-opus-5"
    )
    deepseek_api_key: str = os.environ.get("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.environ.get(
        "ADVANCED_DEEPSEEK_MODEL", "deepseek-v4-flash"
    )
    deepseek_base_url: str = os.environ.get(
        "ADVANCED_DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    ).rstrip("/")
    e2b_api_key: str = os.environ.get("E2B_API_KEY", "")
    e2b_session_timeout: int = int(
        os.environ.get("ADVANCED_E2B_SESSION_TIMEOUT", "120")
    )
    e2b_execution_timeout: int = int(
        os.environ.get("ADVANCED_E2B_EXECUTION_TIMEOUT", "30")
    )
    openai_embed_model: str = os.environ.get(
        "ADVANCED_OPENAI_EMBED_MODEL",
        os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
    )
    oracle_embed_model: str = os.environ.get(
        "ADVANCED_ORACLE_EMBED_MODEL", "ALL_MINILM_L12_V2"
    )
    oracle_embed_native_dimensions: int = int(
        os.environ.get("ADVANCED_ORACLE_EMBED_NATIVE_DIMENSIONS", "384")
    )
    agent_memory_store_id: str = os.environ.get(
        "ADVANCED_AGENT_MEMORY_STORE_ID", "harness_vec1536"
    )
    agent_memory_search_strategy: str = os.environ.get(
        "ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY", "vector"
    ).strip().lower()
    agent_memory_embed_max_tokens: int = int(
        os.environ.get("ADVANCED_AGENT_MEMORY_EMBED_MAX_TOKENS", "8191")
    )
    semantic_backend: str = os.environ.get(
        "ADVANCED_SEMANTIC_BACKEND", "openai"
    ).strip().lower()
    embedding_dimensions: int = int(
        os.environ.get(
            "ADVANCED_EMBEDDING_DIMENSIONS",
            "1536",
        )
    )
    use_model_synthesis: bool = _flag("ADVANCED_USE_MODEL_SYNTHESIS", True)
    skill_promotion_min_occurrences: int = int(
        os.environ.get("ADVANCED_SKILL_PROMOTION_MIN_OCCURRENCES", "2")
    )
    semantic_cache_threshold: float = float(
        os.environ.get("ADVANCED_SEMANTIC_CACHE_THRESHOLD", "0.92")
    )

    app_host: str = os.environ.get("HOST", "127.0.0.1")
    workflow_port: int = int(os.environ.get("WORKFLOW_PORT", "8010"))
    research_port: int = int(os.environ.get("RESEARCH_PORT", "8011"))
    metaharness_port: int = int(os.environ.get("METAHARNESS_PORT", "8012"))
    total_recall_port: int = int(os.environ.get("TOTAL_RECALL_PORT", "8013"))
    def validate_oracle(self) -> None:
        if self.backend != "oracle":
            return
        missing = [
            name
            for name, value in (
                ("ADVANCED_ORA_DSN/ORA_DSN", self.ora_dsn),
                ("ADVANCED_ORA_USER/ORA_AGENT_USER", self.ora_user),
                ("ADVANCED_ORA_PASSWORD/ORA_AGENT_PWD", self.ora_password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError("Oracle mode requires " + ", ".join(missing))

    def oracle_connect_kwargs(self) -> dict[str, object]:
        self.validate_oracle()
        values: dict[str, object] = {
            "user": self.ora_user,
            "password": self.ora_password,
            "dsn": self.ora_dsn,
        }
        if self.ora_wallet_location:
            values["wallet_location"] = self.ora_wallet_location
        if self.ora_wallet_password:
            values["wallet_password"] = self.ora_wallet_password
        return values

    def public_status(self) -> dict[str, object]:
        """Return diagnostics without ever exposing a credential."""

        return {
            "backend": self.backend,
            "oracle_dsn": self.ora_dsn,
            "oracle_user": self.ora_user,
            "oracle_password_configured": bool(self.ora_password),
            "tavily_configured": bool(self.tavily_api_key),
            "research_source": self.research_source,
            "semantic_backend": self.semantic_backend,
            "embedding_dimensions": self.embedding_dimensions,
            "oracle_embedding_model": self.oracle_embed_model,
            "oracle_embedding_native_dimensions": self.oracle_embed_native_dimensions,
            "embedding_key_configured": usable_runtime_secret(self.openai_api_key),
            "agent_memory_search_strategy": self.agent_memory_search_strategy,
            "agent_memory_store_id": self.agent_memory_store_id,
            "openai_model": self.openai_model,
            "anthropic_key_configured": usable_runtime_secret(self.anthropic_api_key),
            "anthropic_model": self.anthropic_model,
            "deepseek_key_configured": usable_runtime_secret(self.deepseek_api_key),
            "deepseek_model": self.deepseek_model,
            "e2b_configured": bool(self.e2b_api_key),
            "e2b_sandbox_egress": "blocked",
            "model_synthesis": self.use_model_synthesis,
            "skill_promotion_min_occurrences": self.skill_promotion_min_occurrences,
        }


settings = AdvancedSettings()
