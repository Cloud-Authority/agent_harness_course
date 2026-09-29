#!/usr/bin/env python3
"""Run one PPA job on one harness through MemoRizz's MetaHarness.

    python metaharness/run_harness.py --doctor
    python metaharness/run_harness.py --harness pi --job morning_brief
    python metaharness/run_harness.py --harness hermes --job inbox_triage --json
    python metaharness/run_harness.py --harness pi --job recall \
        --remember "Keep Friday afternoons free of meetings."

PPA is a personal productivity assistant. A harness is the loop around a model.
This script exports the practice workspace as files, asks one harness (pi,
Hermes, or Claude Code on DeepSeek) to do one job in it, and prints the answer,
the usage and the acceptance anchors.

Every run is read-only: no shell, no network tools, no writes. A harness that is
not ready is reported with its reason and is not run. Nothing is invented for it.

Exit codes: 0 the run succeeded, 1 the run failed, 2 the harness is not ready.
Keys are read from the environment, or from a local ``.env`` file. They are never
printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK))
os.environ.setdefault("PPA_DATA_DIR", str(TRACK / "data" / "cli"))
os.environ.setdefault("PPA_WORKSPACE_DIR", str(TRACK / "workspace" / "cli"))
warnings.filterwarnings("ignore", message="IProgress not found")

from ppa_dfy import harnesses, memory, paths, settings as settings_module  # noqa: E402
from ppa_dfy import workspace_export, world as world_module  # noqa: E402

KEY_FOR_PROVIDER = {"anthropic": "ANTHROPIC_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
                    "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
SUMMARY_FIELDS = ("status", "model", "latency_s", "steps", "tool_calls", "tools_used",
                  "prompt_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
                  "cost_usd", "cost_basis", "memory_tokens", "commands_or_writes",
                  "workspace_unchanged", "error_code", "error", "remediation", "run_id")


def parse_arguments(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one PPA job on one harness and print the result and the usage.")
    parser.add_argument("--harness", choices=harnesses.HARNESS_ORDER, default="pi")
    parser.add_argument("--job", choices=harnesses.job_names(), default="morning_brief")
    parser.add_argument("--question", default="", help="the question for the recall job")
    parser.add_argument("--remember", default="", metavar="STATEMENT",
                        help="store this preference in memory before the run")
    parser.add_argument("--fresh", action="store_true",
                        help="delete this script's memory scope before the run")
    parser.add_argument("--doctor", action="store_true",
                        help="print the readiness of every harness and exit")
    parser.add_argument("--json", action="store_true", help="print one JSON document")
    return parser.parse_args(argv)


def user_id_of(world: Dict[str, Any]) -> str:
    return world_module.owner_email(world).split("@")[0].replace(".", "-")


def stored_preferences(provider: Any, memory_id: str, user_id: str) -> List[Dict[str, Any]]:
    return [row for row in memory.long_term_memories(provider, memory_id=memory_id,
                                                     user_id=user_id)
            if row["kind"] == "preference"]


def print_readiness(rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        state = "ready" if row["ready"] else f"not ready: {row['error_code']}"
        print(f"{row['name']:9} {state:40} {row.get('version') or ''}")
        if not row["ready"]:
            print(f"{'':9} {row.get('error') or ''} {row.get('remediation') or ''}".rstrip())


def print_report(report: Dict[str, Any]) -> None:
    print(f"\n== {report['job']} on {report['harness']} ==")
    for name in SUMMARY_FIELDS:
        value = report["summary"].get(name)
        if value not in (None, "", [], {}):
            print(f"{name:20} {value}")
    print(f"{'memory_sources':20} {len(report['summary']['memory_sources'])}")
    print("\n== acceptance anchors ==")
    for anchor in report["anchors"]:
        print(f"[{anchor['status']:>14}] {anchor['anchor']}: {anchor['evidence']}")
    print("\n== answer ==")
    print(paths.scrub(report["answer"]) or "(the harness returned no text)")


def main(argv: List[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    settings = settings_module.configure_environment()
    world = world_module.load_world()
    manifest = workspace_export.export_workspace(world, paths.workspace_dir())
    workspace = Path(manifest["path"])
    memory_id = os.environ.get("PPA_CLI_MEMORY_ID", "ppa-cli")
    user_id = user_id_of(world)

    provider = memory.make_memory_provider(settings)
    if arguments.fresh:
        memory.reset_scope(provider, memory_id=memory_id, user_id=user_id)
    if arguments.remember:
        memory.remember(provider, arguments.remember, category="preference",
                        memory_id=memory_id, user_id=user_id)
    meta = harnesses.build_meta_harness(provider, workspace, settings)
    try:
        rows = harnesses.readiness(meta)
        if arguments.doctor:
            print_readiness(rows)
            return 0
        probe = next(row for row in rows if row["name"] == arguments.harness)
        if not probe["ready"]:
            row = harnesses.skipped_row(arguments.job, arguments.harness, probe)
            print(json.dumps(row, indent=2) if arguments.json else
                  f"{arguments.harness} is not ready ({probe['error_code']}). "
                  f"{probe.get('error') or ''} {probe.get('remediation') or ''}\n"
                  "The job was not run.")
            return 2
        done = harnesses.run_job(meta, arguments.job, arguments.harness, workspace, settings,
                                 memory_id=memory_id, user_id=user_id,
                                 question=arguments.question)
    finally:
        meta.close()

    answer = done["result"].final_response or ""
    stored = stored_preferences(provider, memory_id, user_id)
    checks = harnesses.evaluate(
        arguments.job, answer, world_module.known_answers(world), world["persona"],
        preference=stored[-1]["content"] if stored else "",
        memory_sources=[row["record_id"] for row in stored])
    report = {"job": arguments.job, "harness": arguments.harness,
              "workspace": paths.display_path(workspace), "files": len(manifest["files"]),
              "summary": done["summary"], "anchors": checks, "answer": paths.scrub(answer)}
    if arguments.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
    return 0 if done["summary"]["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
