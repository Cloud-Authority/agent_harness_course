"""The command line runner, with stand-in executables and no model.

The runner must report a harness that is not ready and stop. It must never
print an answer for a harness it did not run.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

TRACK = Path(__file__).resolve().parents[1]
RUNNER = TRACK / "metaharness" / "run_harness.py"
metaharness = pytest.importorskip("memorizz.metaharness")
if not hasattr(metaharness, "DeepSeekHarness"):
    pytest.skip("this MemoRizz build has no DeepSeek adapter", allow_module_level=True)


def program(folder: Path, name: str, version: str) -> str:
    path = folder / name
    path.write_text(f"#!/bin/sh\necho \"{version}\"\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture()
def environment(tmp_path):
    keep = {name: value for name, value in os.environ.items()
            if not name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}
    keep.update(
        PPA_DATA_DIR=str(tmp_path / "data"), PPA_WORKSPACE_DIR=str(tmp_path / "workspace"),
        PPA_ENV_FILE=str(tmp_path / "no-such.env"), PPA_EMBEDDING_PROVIDER="none",
        ANTHROPIC_API_KEY="placeholder-used-by-an-offline-test",
        MEMORIZZ_PI_COMMAND=program(tmp_path, "pi", "0.87.1"),
        MEMORIZZ_HERMES_COMMAND=program(tmp_path, "hermes", "Hermes Agent v0.21.5 (2026.9.24)"),
        MEMORIZZ_DEEPSEEK_COMMAND=program(tmp_path, "claude", "2.1.284 (Claude Code)"))
    return keep


def run(arguments, environment):
    return subprocess.run([sys.executable, str(RUNNER), *arguments], env=environment,
                          capture_output=True, text=True, timeout=180)


def test_doctor_lists_every_harness_and_exits_cleanly(environment):
    done = run(["--doctor"], environment)
    assert done.returncode == 0, done.stderr[-2000:]
    lines = done.stdout.splitlines()
    assert [line.split()[0] for line in lines if line[:1].isalpha()] == ["pi", "hermes", "deepseek"]
    assert "authentication_required" in done.stdout and "DEEPSEEK_API_KEY" in done.stdout
    assert environment["ANTHROPIC_API_KEY"] not in done.stdout + done.stderr


def test_a_harness_that_is_not_ready_is_not_run(environment):
    done = run(["--harness", "deepseek", "--job", "morning_brief"], environment)
    assert done.returncode == 2
    assert "authentication_required" in done.stdout and "The job was not run." in done.stdout
    assert "== answer ==" not in done.stdout


def test_the_runner_exports_a_locked_workspace_first(environment):
    run(["--doctor"], environment)
    root = Path(environment["PPA_WORKSPACE_DIR"])
    assert (root / "README.md").is_file() and (root / "governed" / "triage.json").is_file()
    assert not os.access(root / "README.md", os.W_OK)
