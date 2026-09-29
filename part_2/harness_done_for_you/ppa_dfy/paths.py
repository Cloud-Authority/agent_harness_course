"""Where this track keeps its files.

Everything generated at run time lives under ``data/`` or ``workspace/``. Both
are ignored by Git, and neither is inside the user's home directory, so a
workshop run never touches a real ``~/.memorizz``, ``~/.pi`` or ``~/.hermes``.
"""
from __future__ import annotations

import os
from pathlib import Path

TRACK_ROOT = Path(__file__).resolve().parents[1]
PART2_ROOT = TRACK_ROOT.parent
REPO_ROOT = PART2_ROOT.parent
SHARED_ROOT = PART2_ROOT / "_shared"
TOOLS_DIR = TRACK_ROOT / ".tools"


def data_dir() -> Path:
    """Folder for generated state. Override with ``PPA_DATA_DIR``."""
    return Path(os.environ.get("PPA_DATA_DIR") or TRACK_ROOT / "data").expanduser().resolve()


def workspace_dir() -> Path:
    """Folder that receives the exported workspace. Override with ``PPA_WORKSPACE_DIR``."""
    return Path(os.environ.get("PPA_WORKSPACE_DIR") or TRACK_ROOT / "workspace").expanduser().resolve()


def memorizz_home() -> Path:
    return data_dir() / "memorizz_home"


def memory_root() -> Path:
    return data_dir() / "memory"


def pi_agent_dir() -> Path:
    return data_dir() / "pi-agent"


def display_path(path: str | Path) -> str:
    """A path safe to print in a saved notebook: relative to the repository.

    Absolute paths reveal the user name and the machine layout, and they make
    saved outputs differ between machines. Paths outside the repository are
    shown with a neutral prefix instead.
    """
    text = str(path)
    for root, label in ((REPO_ROOT, "<repo>"), (Path.home(), "<home>")):
        prefix = str(root)
        if text == prefix:
            return label
        if text.startswith(prefix + os.sep):
            return label + "/" + text[len(prefix) + 1:].replace(os.sep, "/")
    return text


def scrub(text: str) -> str:
    """Replace absolute repository and home prefixes inside free text."""
    value = str(text)
    for root, label in ((REPO_ROOT, "<repo>"), (Path.home(), "<home>")):
        value = value.replace(str(root), label)
    return value
