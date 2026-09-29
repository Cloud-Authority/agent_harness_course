"""Environment configuration and secret handling.

Two rules drive this module.

1. Secrets are read, never shown. Functions report ``True`` or ``False`` for a
   key, and nothing here prints, logs or returns a key to a notebook cell.
2. Generated state stays inside this track. ``configure_environment`` points
   MemoRizz, pi and Hermes at folders under ``data/`` before any of them is
   imported, because each one decides where its home is at import or start-up.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import paths

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
PLACEHOLDERS = {"", "sk-...", "sk-ant-...", "your-key-here", "replace-me", "changeme"}
SECRET_NAMES = ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY",
                "OPENROUTER_API_KEY", "ORACLE_PASSWORD")


def _usable(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() not in PLACEHOLDERS


def has_secret(name: str) -> bool:
    """True when the environment holds a usable value. The value is never returned."""
    return _usable(os.environ.get(name))


def load_env_file(path: Optional[str | Path] = None) -> List[str]:
    """Load ``KEY=value`` lines from a local file without overriding the environment.

    The file is ``PPA_ENV_FILE`` or ``.env`` in this track. It returns the
    names it set, never the values.
    """
    target = Path(path or os.environ.get("PPA_ENV_FILE") or paths.TRACK_ROOT / ".env")
    if not target.is_file():
        return []
    loaded = []
    for line in target.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, _, value = text.partition("=")
        name = name.replace("export ", "").strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ and _usable(value):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def require_secret(name: str, prompt: str) -> bool:
    """Make sure a secret is present, asking without echo when a person is there.

    In a non-interactive run (``PPA_NONINTERACTIVE=1``, or a kernel that cannot
    prompt) a missing secret raises a clear error instead of hanging.
    """
    if has_secret(name):
        return True
    if os.environ.get("PPA_NONINTERACTIVE", "0") == "1":
        raise RuntimeError(f"{name} is not set and this run cannot prompt for it.")
    from getpass import getpass

    try:
        value = getpass(prompt).strip()
    except Exception as exc:  # no terminal, or a kernel without stdin
        raise RuntimeError(f"{name} is not set and no prompt is available.") from exc
    if not _usable(value):
        raise RuntimeError(f"{name} is required for this step.")
    os.environ[name] = value
    return True


def _first_existing(*candidates: Optional[str | Path]) -> Optional[str]:
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate)
        if os.sep in text:
            if Path(text).expanduser().is_file():
                return str(Path(text).expanduser())
        else:
            found = shutil.which(text)
            if found:
                return found
    return None


@dataclass
class Settings:
    """Secret-free settings for one run. Safe to print."""

    model: str
    memory_backend: str
    embedding_provider: Optional[str]
    embedding_model: str
    ollama_url: str
    memory_id: str
    commands: Dict[str, Optional[str]] = field(default_factory=dict)
    harness_models: Dict[str, Dict[str, Optional[str]]] = field(default_factory=dict)
    keys_present: Dict[str, bool] = field(default_factory=dict)

    def public(self) -> Dict[str, object]:
        return {
            "model": self.model,
            "memory_backend": self.memory_backend,
            "embedding": f"{self.embedding_provider}:{self.embedding_model}"
            if self.embedding_provider else "none (keyword recall)",
            "memory_id": self.memory_id,
            "data_dir": paths.display_path(paths.data_dir()),
            "commands": {name: paths.display_path(value) if value else None
                         for name, value in self.commands.items()},
            "harness_models": self.harness_models,
            "keys_present": self.keys_present,
        }


def configure_environment() -> Settings:
    """Point every tool at this track's folders and return secret-free settings.

    Call this before importing ``memorizz``. It is safe to call again.
    """
    load_env_file()
    for folder in (paths.data_dir(), paths.memorizz_home(), paths.memory_root(), paths.pi_agent_dir()):
        folder.mkdir(parents=True, exist_ok=True)

    # These three are forced, not defaulted: an inherited MEMORIZZ_HOME would
    # make the workshop write into the user's real MemoRizz home.
    os.environ["MEMORIZZ_HOME"] = str(paths.memorizz_home())
    os.environ["MEMORIZZ_MEMORY_ROOT"] = str(paths.memory_root())
    os.environ["PI_CODING_AGENT_DIR"] = str(paths.pi_agent_dir())

    model = os.environ.setdefault("PPA_MODEL", DEFAULT_MODEL)
    commands = {
        "pi": _first_existing(os.environ.get("MEMORIZZ_PI_COMMAND"),
                              paths.TOOLS_DIR / "node_modules" / ".bin" / "pi", "pi"),
        "hermes": _first_existing(os.environ.get("MEMORIZZ_HERMES_COMMAND"),
                                  paths.TOOLS_DIR / "hermes-venv" / "bin" / "hermes", "hermes"),
        "deepseek": _first_existing(os.environ.get("MEMORIZZ_DEEPSEEK_COMMAND"), "claude",
                                    Path.home() / ".local" / "bin" / "claude"),
    }
    for name, value in commands.items():
        if value:
            os.environ[f"MEMORIZZ_{name.upper()}_COMMAND"] = value

    # pi and Hermes take any provider they support. Anthropic is the default
    # because it is the key this workshop has; set these to switch provider.
    os.environ.setdefault("MEMORIZZ_PI_PROVIDER", "anthropic")
    os.environ.setdefault("MEMORIZZ_PI_MODEL", model)
    os.environ.setdefault("MEMORIZZ_HERMES_PROVIDER", "anthropic")
    os.environ.setdefault("MEMORIZZ_HERMES_MODEL", model)

    embedding_provider = os.environ.get("PPA_EMBEDDING_PROVIDER", "ollama").strip().lower()
    return Settings(
        model=model,
        memory_backend=os.environ.get("PPA_MEMORY_BACKEND", "filesystem").strip().lower(),
        embedding_provider=None if embedding_provider in {"", "none", "off"} else embedding_provider,
        embedding_model=os.environ.get("PPA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        ollama_url=os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_URL,
        memory_id=os.environ.get("PPA_MEMORY_ID", "ppa-workshop"),
        commands=commands,
        harness_models={
            "pi": {"provider": os.environ.get("MEMORIZZ_PI_PROVIDER"),
                   "model": os.environ.get("MEMORIZZ_PI_MODEL")},
            "hermes": {"provider": os.environ.get("MEMORIZZ_HERMES_PROVIDER"),
                       "model": os.environ.get("MEMORIZZ_HERMES_MODEL"),
                       "base_url": os.environ.get("MEMORIZZ_HERMES_BASE_URL")},
            "deepseek": {"provider": "deepseek",
                         "model": os.environ.get("MEMORIZZ_DEEPSEEK_MODEL") or "deepseek-flash"},
        },
        keys_present={name: has_secret(name) for name in SECRET_NAMES},
    )
