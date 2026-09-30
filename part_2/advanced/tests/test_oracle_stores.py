"""The MemoRizz stores on Oracle AI Database, when the database and the MemoRizz source are there."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

from conftest import needs_oracle

SRC = Path(os.path.expanduser(os.getenv("MEMORIZZ_SRC", "~/Desktop/memorizz/src")))
if (SRC / "memorizz").is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
memorizz = pytest.importorskip("memorizz")


@needs_oracle
def test_runs_events_and_approvals_round_trip():
    from memorizz.approval import ApprovalStatus
    from memorizz.metaharness.models import HarnessEvent, HarnessEventType, HarnessRun, HarnessStatus

    from shared import oracle
    from shared.memorizz_oracle_stores import OracleApprovalStore, OracleHarnessRunStore

    pool = oracle.pool("test-mh", max=2)
    runs = OracleHarnessRunStore(pool, prefix="MHTEST")
    approvals = OracleApprovalStore(pool, prefix="MHTEST")
    run_id = f"test-{uuid.uuid4().hex[:8]}"
    run = HarnessRun(run_id=run_id, task={"task": "t", "workspace": "/tmp"}, status=HarnessStatus.QUEUED, harness="codex")
    runs.create(run)
    assert runs.get(run_id).status == HarnessStatus.QUEUED
    runs.update(run_id, status=HarnessStatus.RUNNING.value)
    assert runs.get(run_id).status == HarnessStatus.RUNNING
    runs.append_event(HarnessEvent(run_id=run_id, type=HarnessEventType.MESSAGE, data={"text": "hi"}))
    runs.append_event(HarnessEvent(run_id=run_id, type=HarnessEventType.MESSAGE, data={"text": "again"}))
    assert [e.sequence for e in runs.events(run_id)] == [1, 2]
    assert runs.acquire_workspace("/tmp/ws", run_id) is True and runs.acquire_workspace("/tmp/ws", "other") is False
    runs.release_workspace("/tmp/ws", run_id)
    assert runs.recover_interrupted() >= 1 and runs.get(run_id).status == HarnessStatus.INTERRUPTED

    proposal = approvals.propose(owner_id="me", tool_name="metaharness.run", arguments={"a": 1}, policy_reason="edits")
    assert proposal.status == ApprovalStatus.PENDING
    approved = approvals.approve(proposal.proposal_id, approver_id="reviewer")
    assert approved.status == ApprovalStatus.APPROVED
    consumed = approvals.consume(proposal.proposal_id, expected_tool_name="metaharness.run", expected_arguments={"a": 1})
    assert consumed.status == ApprovalStatus.CONSUMED
    with pytest.raises(Exception):
        approvals.consume(proposal.proposal_id)
    oracle.close()
