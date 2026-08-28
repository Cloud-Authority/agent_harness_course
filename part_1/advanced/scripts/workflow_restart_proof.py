#!/usr/bin/env python3
"""Prove Oracle recovery with three fresh Python processes.

Run from the course root after configuring the local Oracle service:

    .venv/bin/python part_1/advanced/scripts/workflow_restart_proof.py

The parent never imports the workflow runtime. It launches a crash phase, a resume
phase, and an approval phase; each child creates a new pool, OracleSaver, OracleStore,
OracleAgentMemory client, report drafter, and compiled LangGraph instance around the
same ``thread_id``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


COURSE_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).resolve()


def child(phase: str, thread_id: str) -> dict:
    sys.path.insert(0, str(COURSE_ROOT))
    from part_1.advanced.shared.workflow import WorkflowHarness

    harness = WorkflowHarness()
    try:
        if harness.resources.backend != "oracle":
            raise RuntimeError(
                "Cross-process restart proof requires ADVANCED_BACKEND=oracle"
            )
        if phase == "crash":
            result = harness.start(
                thread_id=thread_id,
                fail_once_at="draft_report",
                requested_by="restart-proof-process-a",
            )
            assert result["status"] == "resumable"
            assert result["next"] == ["draft_report"]
        elif phase == "resume":
            result = harness.resume_after_failure(thread_id)
            assert result["status"] == "pending_approval"
            assert any(
                item["operation"] == "draft_report" and item["reused"]
                for item in result["state"]["idempotency"]
            )
        elif phase == "approve":
            result = harness.decide(
                thread_id,
                approved=True,
                decided_by="restart-proof-host",
                comment="Approved in a third clean Python process.",
            )
            assert result["status"] == "published"
        else:
            raise ValueError(f"Unknown phase: {phase}")
        return {
            "phase": phase,
            "thread_id": thread_id,
            "status": result["status"],
            "next": result["next"],
            "checkpoint_count": len(result["checkpoint_history"]),
            "idempotency": result["state"].get("idempotency", []),
            "persistence": result["persistence"],
        }
    finally:
        harness.close()


def orchestrate(thread_id: str) -> None:
    evidence = []
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(COURSE_ROOT)
    # This script isolates process durability from paid/model/provider variance.
    # The main runtime defaults remain OpenAI vector + model + E2B when valid keys
    # are supplied.
    environment.update(
        {
            "ADVANCED_BACKEND": "oracle",
            "ADVANCED_SEMANTIC_BACKEND": "hash",
            "ADVANCED_EMBEDDING_DIMENSIONS": "1536",
            "ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY": "keyword",
            "ADVANCED_AGENT_MEMORY_STORE_ID": "harness_kw",
            "ADVANCED_USE_MODEL_SYNTHESIS": "false",
            "E2B_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
    )
    for phase in ("crash", "resume", "approve"):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--phase", phase, "--thread-id", thread_id],
            cwd=COURSE_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        evidence.append(json.loads(completed.stdout))
    assert [item["status"] for item in evidence] == [
        "resumable",
        "pending_approval",
        "published",
    ]
    assert all(item["persistence"]["backend"] == "oracle" for item in evidence)
    print(json.dumps({"ok": True, "processes": 3, "evidence": evidence}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("crash", "resume", "approve"))
    parser.add_argument("--thread-id")
    args = parser.parse_args()
    thread_id = args.thread_id or f"restart-proof-{uuid.uuid4().hex[:12]}"
    if args.phase:
        print(json.dumps(child(args.phase, thread_id)))
    else:
        orchestrate(thread_id)


if __name__ == "__main__":
    main()
