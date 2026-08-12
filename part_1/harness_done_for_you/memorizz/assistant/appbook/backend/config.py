"""Single settings object shared by the MemoRizz appbook and notebook.

The appbook never stores secrets.  It reads the same environment-variable names used
by the standalone notebook and exposes only boolean readiness signals to the browser.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
COURSE_ROOT = APP_DIR.parents[4]
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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


for candidate in (COURSE_ROOT / ".env", APP_DIR / ".env"):
    _load_env(candidate)


@dataclass(frozen=True)
class Settings:
    mode: str = os.environ.get("ERPA_MODE", "local")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("MEMORIZZ_LLM_MODEL", os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    oracle_dsn: str = os.environ.get("ORACLE_DSN", "127.0.0.1:1522/FREEPDB1")
    oracle_user: str = os.environ.get("ORACLE_USER", "MEMORIZZ_COURSE")
    oracle_password: str = os.environ.get("ORACLE_PASSWORD", "")
    oracle_admin_password: str = os.environ.get("ORACLE_ADMIN_PASSWORD", "")
    oracle_container: str = os.environ.get("ERPA_ORACLE_CONTAINER", "erpa-memorizz-oracle")
    oracle_image: str = os.environ.get(
        "ERPA_ORACLE_IMAGE", "container-registry.oracle.com/database/free:latest"
    )
    embedding_backend: str = os.environ.get("ERPA_EMBEDDING_BACKEND", "oracle")
    notion_mcp_token: str = os.environ.get("NOTION_MCP_TOKEN", "")
    # Compatibility endpoints use the direct Notion REST API rather than MCP.
    # Accept either variable so optional tools fall back to fixtures cleanly.
    notion_api_key: str = os.environ.get(
        "NOTION_API_KEY", os.environ.get("NOTION_MCP_TOKEN", "")
    )
    notion_mcp_redirect_uri: str = os.environ.get(
        "NOTION_MCP_REDIRECT_URI", "http://127.0.0.1:8765/callback"
    )
    tavily_api_key: str = os.environ.get("TAVILY_API_KEY", "")
    google_calendar_credentials: str = os.environ.get(
        "GOOGLE_CALENDAR_CREDENTIALS", ""
    )
    e2b_api_key: str = os.environ.get("E2B_API_KEY", "")
    # A configured key opts into the real sandbox by default. Set ERPA_RUN_E2B=0
    # explicitly when a credential is present but remote execution is undesired.
    run_e2b: bool = _env_bool("ERPA_RUN_E2B", bool(os.environ.get("E2B_API_KEY")))
    e2b_template: str = os.environ.get("ERPA_E2B_TEMPLATE", "")
    memorizz_observability: bool = _env_bool("ERPA_MEMORIZZ_OBSERVABILITY", True)
    memorizz_ui_url: str = os.environ.get("MEMORIZZ_UI_URL", "http://127.0.0.1:8765")
    local_memory_path: Path = DATA_DIR / "memorizz_local.db"

    @property
    def live(self) -> bool:
        return self.mode.lower() == "live"

    @property
    def oracle_configured(self) -> bool:
        return bool(self.oracle_dsn and self.oracle_user and self.oracle_password)

    @property
    def execution_profile(self) -> str:
        return "live Oracle + MemoRizz" if self.live else "deterministic teaching profile"


settings = Settings()
