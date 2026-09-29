"""Scan the saved notebooks for secrets and machine-specific paths.

    python scripts/scan_notebooks.py

A notebook that is saved with outputs can leak what a cell printed. This scan
reads every source and output of both notebooks and fails when it finds a key
prefix, an absolute home path, or a user name. It exits with status 1 on a
finding, so it can guard a commit.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
NOTEBOOKS = (TRACK / "memorizz" / "assistant" / "notebook" / "ppa_memorizz_complete.ipynb",
             TRACK / "metaharness" / "notebook" / "ppa_metaharness_pi_deepseek_hermes.ipynb")
PATTERNS = {
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    "Tavily key": re.compile(r"tvly-[A-Za-z0-9_-]{8,}"),
    "generic secret key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}"),
    "absolute home path": re.compile(r"/(Users|home)/[A-Za-z0-9._-]+/"),
    "temporary folder path": re.compile(r"/private/(tmp|var)/|/var/folders/"),
}


def cell_text(cell: dict) -> str:
    """Every string a cell holds: its source and all of its outputs."""
    parts = ["".join(cell.get("source", []))]
    for output in cell.get("outputs", []):
        parts.append("".join(output.get("text", [])))
        parts.append(json.dumps(output.get("data", {})))
        parts.append("\n".join(output.get("traceback", [])))
    return "\n".join(parts)


def secret_values() -> dict[str, str]:
    """Values in this environment that must never appear in a notebook."""
    names = [name for name in os.environ if re.search(r"(API_KEY|TOKEN|SECRET|PASSWORD)$", name)]
    found = {name: os.environ[name] for name in names if len(os.environ[name]) >= 12}
    found["user name"] = getpass.getuser()
    return found


def scan(path: Path) -> list[str]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    findings = []
    for index, cell in enumerate(notebook["cells"]):
        text = cell_text(cell)
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.name} cell {index}: {label}")
        for label, value in secret_values().items():
            if value and value in text:
                findings.append(f"{path.name} cell {index}: the value of {label}")
    return findings


def main() -> int:
    findings, scanned = [], 0
    for path in NOTEBOOKS:
        if path.is_file():
            scanned += 1
            findings += scan(path)
    for line in findings:
        print("FOUND", line)
    print(f"scanned {scanned} notebook(s): {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
