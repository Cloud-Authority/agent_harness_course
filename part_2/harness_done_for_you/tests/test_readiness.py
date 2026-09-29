"""Readiness probes, with stand-in executables and no model.

A harness that cannot run has to say why. These tests give each adapter a small
script that only prints a version, and check the error code for a missing
program, an old program and a missing key.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

metaharness = pytest.importorskip("memorizz.metaharness")
if not all(hasattr(metaharness, name) for name in ("PiHarness", "HermesHarness", "DeepSeekHarness")):
    pytest.skip("this MemoRizz build has no pi, Hermes or DeepSeek adapter",
                allow_module_level=True)

KEYS = ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY")
PLACEHOLDER = "placeholder-used-by-an-offline-test"


def program(folder: Path, name: str, version: str) -> str:
    """An executable that prints a version line and does nothing else."""
    path = folder / name
    path.write_text(f"#!/bin/sh\necho \"{version}\"\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture()
def no_keys(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)


def probe(adapter) -> dict:
    return adapter.probe().to_dict()


def test_a_missing_program_is_reported_as_unavailable(tmp_path, no_keys):
    missing = str(tmp_path / "not-installed")
    adapters = [metaharness.PiHarness(command=missing, provider="anthropic"),
                metaharness.HermesHarness(command=missing, provider="anthropic"),
                metaharness.DeepSeekHarness(command=missing)]
    for adapter in adapters:
        row = probe(adapter)
        assert (row["ready"], row["available"]) == (False, False)
        assert row["error_code"] == "harness_unavailable"


def test_deepseek_without_a_key_needs_authentication(tmp_path, no_keys):
    command = program(tmp_path, "claude", "2.1.284 (Claude Code)")
    row = probe(metaharness.DeepSeekHarness(command=command))
    assert row["available"] is True and row["ready"] is False
    assert row["error_code"] == "authentication_required"
    assert "DEEPSEEK_API_KEY" in row["error"] and row["remediation"]


def test_deepseek_with_a_key_is_ready_and_the_key_is_not_in_the_row(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", PLACEHOLDER)
    command = program(tmp_path, "claude", "2.1.284 (Claude Code)")
    row = probe(metaharness.DeepSeekHarness(command=command))
    assert row["ready"] is True and row["error_code"] is None
    assert PLACEHOLDER not in str(row)


def test_hermes_without_a_key_needs_authentication(tmp_path, no_keys):
    command = program(tmp_path, "hermes", "Hermes Agent v0.21.5 (2026.9.24)")
    row = probe(metaharness.HermesHarness(command=command, provider="anthropic"))
    assert row["available"] is True and row["error_code"] == "authentication_required"


def test_an_old_hermes_is_rejected_with_a_remedy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER)
    command = program(tmp_path, "hermes", "Hermes Agent v0.19.0 (2026.5.1)")
    row = probe(metaharness.HermesHarness(command=command, provider="anthropic"))
    assert row["ready"] is False and row["error_code"] == "harness_unavailable"
    assert "0.21.4" in row["error"] and row["remediation"]


def test_the_readiness_table_lists_three_harnesses_without_secrets(tmp_path, monkeypatch, world):
    from ppa_dfy import harnesses, memory, settings as settings_module

    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("PPA_EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("MEMORIZZ_PI_COMMAND", program(tmp_path, "pi", "0.87.1"))
    monkeypatch.setenv("MEMORIZZ_HERMES_COMMAND",
                       program(tmp_path, "hermes", "Hermes Agent v0.21.5 (2026.9.24)"))
    monkeypatch.setenv("MEMORIZZ_DEEPSEEK_COMMAND",
                       program(tmp_path, "claude", "2.1.284 (Claude Code)"))
    settings = settings_module.configure_environment()
    provider = memory.make_memory_provider(settings)
    meta = harnesses.build_meta_harness(provider, tmp_path, settings)
    try:
        rows = harnesses.readiness(meta)
    finally:
        meta.close()
    assert [row["name"] for row in rows] == list(harnesses.HARNESS_ORDER)
    by_name = {row["name"]: row for row in rows}
    assert by_name["hermes"]["ready"] is True
    assert by_name["deepseek"]["error_code"] == "authentication_required"
    assert PLACEHOLDER not in str(rows) and str(Path.home()) not in str(rows)
    skipped = harnesses.skipped_row("morning_brief", "deepseek", by_name["deepseek"])
    assert skipped["status"].startswith("skipped") and "answer" not in skipped
