"""Run the three-stage plan of the meta-harness lesson from the command line.

pi plans, Codex implements behind an approval, Claude Code reviews. Memory, the
run ledger and the approval queue live in Oracle AI Database.

    MEMORIZZ_SRC=~/Desktop/memorizz/src python part_2/advanced/scripts/metaharness_plan_demo.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

ADVANCED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADVANCED))
source = os.environ.get("MEMORIZZ_SRC", "")
if source:
    sys.path.insert(0, os.path.expanduser(source))
TOOLS = ADVANCED.parent / "harness_done_for_you" / ".tools"
os.environ.setdefault("MEMORIZZ_PI_COMMAND", str(TOOLS / "node_modules" / ".bin" / "pi"))
os.environ.setdefault("MEMORIZZ_HERMES_COMMAND", str(TOOLS / "hermes-venv" / "bin" / "hermes"))
logging.getLogger().setLevel(logging.ERROR)

from shared import oracle  # noqa: E402
from shared.memorizz_oracle_patch import patch_oracle_provider  # noqa: E402
from shared.memorizz_oracle_stores import OracleApprovalStore, OracleHarnessRunStore  # noqa: E402
from metaharness_workspace import write_workspace  # noqa: E402

patch_oracle_provider()
from memorizz.memory_provider.oracle import OracleConfig, OracleProvider  # noqa: E402
from memorizz.metaharness import MetaHarness  # noqa: E402

TASK = ("In tripbook/ledger.py, a booking that was cancelled is replayed by book() as if it were still confirmed. "
        "Booking the same offer again after a cancel must create a new confirmed booking. Keep the change minimal, "
        "keep the public API, and keep python -m pytest -q green.")
STAGES = [
    {"name": "Plan", "harness": "pi", "instruction": "Write a short plan for the fix and the test to add. Do not edit files."},
    {"name": "Implement", "harness": "codex", "workspace_mode": "direct", "verification": {"command": "python -m pytest -q"}},
    {"name": "Review", "harness": "claude-code",
     "instruction": "Review the change made in this workspace against the task. Do not edit files. Say whether it is correct and minimal."},
]


def main() -> None:
    workspace = write_workspace(Path("~/.ppa_workshop/metaharness-workspace").expanduser())
    provider = OracleProvider(OracleConfig(user=oracle.ORA.user, password=oracle.ORA.password, dsn=oracle.ORA.dsn,
                                           in_database_embedding=True, pool_max=4))
    pool = oracle.pool("mh", max=4)
    meta = MetaHarness.from_env(memory_provider=provider, run_store=OracleHarnessRunStore(pool, "MH"),
                                approval_store=OracleApprovalStore(pool, "MH"), allowed_workspace_roots=[str(workspace)])
    started = meta.start_plan({"task": TASK, "workspace": str(workspace), "memory_id": "tripbook", "user_id": "richmond",
                               "thread_id": "ledger-fix"}, STAGES)
    oid = started["orchestration_id"]
    print("orchestration", oid, flush=True)
    t0, approved = time.perf_counter(), set()
    while True:
        time.sleep(5)
        record = meta.get_orchestration(oid)
        status = record["status"] if isinstance(record, dict) else record.status.value
        steps = record["steps"] if isinstance(record, dict) else record.steps
        for proposal in meta.approval_store.list(status="pending"):
            if proposal.proposal_id not in approved:
                approved.add(proposal.proposal_id)
                print(f"[{time.perf_counter() - t0:4.0f}s] approval needed for {proposal.tool_name}: {proposal.policy_reason[:90]}", flush=True)
                meta.approve(proposal.proposal_id, approver_id="richmond@workshop")
                run = meta.resume_approval_start(proposal.proposal_id)
                print(f"        approved; resumed run {run.run_id}", flush=True)
        line = " | ".join(f"{s.get('name')}:{s.get('harness')}:"
                          f"{meta.run_store.get(s['run_id']).status.value if s.get('run_id') else '-'}" for s in steps)
        print(f"[{time.perf_counter() - t0:4.0f}s] {status:<16} {line}", flush=True)
        if status in ("succeeded", "failed", "canceled", "interrupted") or time.perf_counter() - t0 > 1200:
            break
    for step in steps:
        run = meta.run_store.get(step["run_id"]) if step.get("run_id") else None
        if run:
            result = run.result or {}
            print(f"\n== {step['name']} on {run.harness}: {run.status.value} verified={result.get('verified')} "
                  f"cost={result.get('cost_usd')} latency_ms={result.get('latency_ms')}")
            print((result.get("final_response") or "")[:700])
            if result.get("workspace_diff"):
                print("diff:\n" + result["workspace_diff"][:900])
    error = record.get("error") if isinstance(record, dict) else record.error
    print("\nplan error:", error)
    print("conversation memory rows:", oracle.rows("SELECT COUNT(*) AS n FROM conversation_memory"))
    oracle.close()


if __name__ == "__main__":
    main()
