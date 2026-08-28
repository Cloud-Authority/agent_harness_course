"""Configuration shared by the Total Recall notebook and appbook."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = APP_DIR / "backend"
FRONTEND_DIR = APP_DIR / "frontend"
PROJECT_ROOT = APP_DIR.parents[3]

for candidate in (PROJECT_ROOT / ".env", APP_DIR / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=False)


def _configured_secret(value: str) -> str:
    """Return a real-looking configured value, never an example placeholder."""
    cleaned = (value or "").strip()
    normalized = cleaned.lower().replace("…", "...")
    if (
        not normalized
        or normalized in {"sk-...", "...", "your_api_key_here", "your-openai-api-key"}
        or "your_api_key" in normalized
    ):
        return ""
    return cleaned


class Settings:
    ora_user: str = os.environ.get(
        "ADVANCED_ORA_USER", os.environ.get("ORA_AGENT_USER", "AGENT")
    )
    ora_password: str = os.environ.get(
        "ADVANCED_ORA_PASSWORD", os.environ.get("ORA_AGENT_PWD", "")
    )
    ora_dsn: str = os.environ.get(
        "ADVANCED_ORA_DSN", os.environ.get("ORA_DSN", "localhost:1523/FREEPDB1")
    )
    oracle_enabled: bool = os.environ.get("ORACLE_ENABLED", "1").lower() not in {
        "0",
        "false",
    }

    embed_model: str = os.environ.get("EMBED_MODEL", "ALL_MINILM_L12_V2")
    rerank_model: str = os.environ.get("RERANK_MODEL", "RERANK_XENC")
    vector_dim: int = int(os.environ.get("VECTOR_DIM", "384"))
    oamp_store_id: str = os.environ.get(
        "OAMP_STORE_ID", os.environ.get("OAMP_PREFIX", "OAMP_").rstrip("_")
    )

    openai_api_key: str = _configured_secret(os.environ.get("OPENAI_API_KEY", ""))
    model: str = "gpt-5.5"
    max_output_tokens: int = int(os.environ.get("TR_MAX_OUTPUT_TOKENS", "2048"))
    reasoning_effort: str = "low"

    user_id: str = os.environ.get("TR_USER_ID", "appbook_user")
    agent_id: str = os.environ.get("TR_AGENT_ID", "total_recall")


settings = Settings()
