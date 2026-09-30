"""MemoRizz meta-harness state in Oracle AI Database: the run ledger and the approval queue.

MemoRizz ships these two stores on SQLite for one local worker. The contracts
are small protocols, so a host can keep the same records in the database it
already runs on. Rows carry the record as JSON beside the columns that are
queried, which keeps the store honest when MemoRizz adds a field.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import oracledb
from memorizz.approval import (ApprovalMismatch, ApprovalNotFound, ApprovalProposal, ApprovalStateError,
                               ApprovalStatus, argument_hash, canonical_arguments)
from memorizz.metaharness.models import (HarnessEvent, HarnessOrchestration, HarnessRun, HarnessStatus,
                                         utcnow_iso)

ALREADY_THERE = ("ORA-00955", "ORA-01430", "ORA-02260")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _when(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value))


class OracleTables:
    """What the two stores share: a pool, a prefix and idempotent DDL."""

    def __init__(self, pool: Any, prefix: str = "MH") -> None:
        self.pool, self.prefix = pool, prefix.upper()
        self._create()

    def table(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    def _ddl(self, cursor: Any, statement: str) -> None:
        try:
            cursor.execute(statement)
        except oracledb.DatabaseError as error:
            if not str(error).startswith(ALREADY_THERE):
                raise

    def _create(self) -> None:
        t = self.table
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            self._ddl(cursor, f"""CREATE TABLE {t('RUNS')} (
                run_id VARCHAR2(80) PRIMARY KEY, status VARCHAR2(30) NOT NULL, harness VARCHAR2(60),
                created_at VARCHAR2(40) NOT NULL, updated_at VARCHAR2(40) NOT NULL, payload CLOB NOT NULL)""")
            self._ddl(cursor, f"""CREATE TABLE {t('EVENTS')} (
                run_id VARCHAR2(80) NOT NULL, sequence NUMBER NOT NULL, timestamp VARCHAR2(40) NOT NULL,
                event_type VARCHAR2(60) NOT NULL, item_id VARCHAR2(200), payload CLOB NOT NULL,
                CONSTRAINT {t('EVENTS')}_PK PRIMARY KEY (run_id, sequence))""")
            self._ddl(cursor, f"""CREATE TABLE {t('LEASES')} (
                workspace VARCHAR2(1000) PRIMARY KEY, run_id VARCHAR2(80) NOT NULL, acquired_at VARCHAR2(40) NOT NULL)""")
            self._ddl(cursor, f"""CREATE TABLE {t('ORCHESTRATIONS')} (
                orchestration_id VARCHAR2(80) PRIMARY KEY, kind VARCHAR2(20) NOT NULL, status VARCHAR2(30) NOT NULL,
                created_at VARCHAR2(40) NOT NULL, updated_at VARCHAR2(40) NOT NULL, payload CLOB NOT NULL)""")
            self._ddl(cursor, f"""CREATE TABLE {t('APPROVALS')} (
                proposal_id VARCHAR2(80) PRIMARY KEY, owner_id VARCHAR2(200) NOT NULL, tool_name VARCHAR2(200) NOT NULL,
                arguments_json CLOB NOT NULL, argument_hash VARCHAR2(128) NOT NULL, policy_reason VARCHAR2(2000) NOT NULL,
                checkpoint_json CLOB NOT NULL, status VARCHAR2(20) NOT NULL, created_at VARCHAR2(40) NOT NULL,
                expires_at VARCHAR2(40) NOT NULL, approver_id VARCHAR2(200), decision_reason VARCHAR2(2000),
                decided_at VARCHAR2(40), consumed_at VARCHAR2(40))""")
            connection.commit()


class OracleRuns(OracleTables):
    """Runs: create, read, list, update."""

    def create(self, run: HarnessRun) -> HarnessRun:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {self.table('RUNS')} (run_id, status, harness, created_at, updated_at, payload) "
                           "VALUES (:1, :2, :3, :4, :5, :6)",
                           [run.run_id, run.status.value, run.harness, run.created_at, run.updated_at, _dump(run.to_dict())])
            connection.commit()
        return run

    def get(self, run_id: str) -> HarnessRun | None:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('RUNS')} WHERE run_id = :1", [str(run_id)])
            row = cursor.fetchone()
        return HarnessRun(**json.loads(row[0])) if row else None

    def list(self, *, limit: int = 100, status: str | None = None) -> list[HarnessRun]:
        where = " WHERE status = :status" if status else ""
        binds = {"limit": max(1, min(int(limit), 10_000)), **({"status": str(status)} if status else {})}
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('RUNS')}{where} ORDER BY updated_at DESC "
                           "FETCH FIRST :limit ROWS ONLY", binds)
            return [HarnessRun(**json.loads(row[0])) for row in cursor.fetchall()]

    def update(self, run_id: str, **changes: Any) -> HarnessRun:
        """A read-modify-write under a row lock, so two hosts cannot erase each other's change."""
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('RUNS')} WHERE run_id = :1 FOR UPDATE", [str(run_id)])
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"Unknown harness run: {run_id}")
            payload = HarnessRun(**json.loads(row[0])).to_dict()
            payload.update(changes)
            payload["updated_at"] = utcnow_iso()
            updated = HarnessRun(**payload)
            cursor.execute(f"UPDATE {self.table('RUNS')} SET status = :1, harness = :2, updated_at = :3, payload = :4 "
                           "WHERE run_id = :5", [updated.status.value, updated.harness, updated.updated_at,
                                                  _dump(updated.to_dict()), updated.run_id])
            connection.commit()
        return updated


class OracleEvents(OracleTables):
    """Events: numbered per run as they are appended."""

    def append_event(self, event: HarnessEvent) -> HarnessEvent:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            if event.sequence is None:
                cursor.execute(f"SELECT COALESCE(MAX(sequence), 0) FROM {self.table('EVENTS')} WHERE run_id = :1",
                               [event.run_id])
                event.sequence = int(cursor.fetchone()[0]) + 1
            item = (event.data or {}).get("id") if isinstance(event.data, dict) else None
            cursor.execute(f"INSERT INTO {self.table('EVENTS')} (run_id, sequence, timestamp, event_type, item_id, payload) "
                           "VALUES (:1, :2, :3, :4, :5, :6)",
                           [event.run_id, event.sequence, event.timestamp, event.type.value,
                            str(item)[:200] if item else None, _dump(event.to_dict())])
            connection.commit()
        return event

    def events(self, run_id: str, *, after: int = 0, limit: int = 1000) -> list[HarnessEvent]:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('EVENTS')} WHERE run_id = :1 AND sequence > :2 "
                           "ORDER BY sequence FETCH FIRST :3 ROWS ONLY",
                           [str(run_id), max(0, int(after)), max(1, min(int(limit), 10_000))])
            return [HarnessEvent(**json.loads(row[0])) for row in cursor.fetchall()]

    def event_counts(self, run_ids: list[str]) -> dict[str, dict[str, int]]:
        ids = [str(r) for r in run_ids if r][:1000]
        if not ids:
            return {}
        marks = ", ".join(f":i{n}" for n in range(len(ids)))
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT run_id, event_type, COUNT(DISTINCT COALESCE(item_id, TO_CHAR(sequence))) "
                           f"FROM {self.table('EVENTS')} WHERE run_id IN ({marks}) GROUP BY run_id, event_type",
                           {f"i{n}": r for n, r in enumerate(ids)})
            counts: dict[str, dict[str, int]] = {}
            for run_id, kind, n in cursor.fetchall():
                counts.setdefault(run_id, {})[kind] = int(n)
        return counts


class OracleLeases(OracleTables):
    """Workspace leases: one row per workspace, so two runs cannot edit the same tree at once."""

    def acquire_workspace(self, workspace: str, run_id: str) -> bool:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            try:
                cursor.execute(f"INSERT INTO {self.table('LEASES')} (workspace, run_id, acquired_at) VALUES (:1, :2, :3)",
                               [str(workspace), str(run_id), utcnow_iso()])
                connection.commit()
                return True
            except oracledb.IntegrityError:
                connection.rollback()
                return False

    def release_workspace(self, workspace: str, run_id: str) -> None:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {self.table('LEASES')} WHERE workspace = :1 AND run_id = :2",
                           [str(workspace), str(run_id)])
            connection.commit()


class OracleOrchestrations(OracleTables):
    """Plans and comparisons: a record with steps, updated under a row lock."""

    def create_orchestration(self, orchestration: HarnessOrchestration) -> HarnessOrchestration:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {self.table('ORCHESTRATIONS')} (orchestration_id, kind, status, created_at, "
                           "updated_at, payload) VALUES (:1, :2, :3, :4, :5, :6)",
                           [orchestration.orchestration_id, orchestration.kind, orchestration.status.value,
                            orchestration.created_at, orchestration.updated_at, _dump(orchestration.to_dict())])
            connection.commit()
        return orchestration

    def get_orchestration(self, orchestration_id: str) -> HarnessOrchestration | None:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('ORCHESTRATIONS')} WHERE orchestration_id = :1",
                           [str(orchestration_id)])
            row = cursor.fetchone()
        return HarnessOrchestration(**json.loads(row[0])) if row else None

    def list_orchestrations(self, *, limit: int = 50, status: str | None = None) -> list[HarnessOrchestration]:
        where = " WHERE status = :status" if status else ""
        binds = {"limit": max(1, min(int(limit), 10_000)), **({"status": str(status)} if status else {})}
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('ORCHESTRATIONS')}{where} ORDER BY updated_at DESC "
                           "FETCH FIRST :limit ROWS ONLY", binds)
            return [HarnessOrchestration(**json.loads(row[0])) for row in cursor.fetchall()]

    def update_orchestration(self, orchestration_id: str, **changes: Any) -> HarnessOrchestration:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT payload FROM {self.table('ORCHESTRATIONS')} WHERE orchestration_id = :1 FOR UPDATE",
                           [str(orchestration_id)])
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"Unknown orchestration: {orchestration_id}")
            payload = HarnessOrchestration(**json.loads(row[0])).to_dict()
            payload.update(changes)
            payload["updated_at"] = utcnow_iso()
            updated = HarnessOrchestration(**payload)
            cursor.execute(f"UPDATE {self.table('ORCHESTRATIONS')} SET status = :1, updated_at = :2, payload = :3 "
                           "WHERE orchestration_id = :4",
                           [updated.status.value, updated.updated_at, _dump(updated.to_dict()), updated.orchestration_id])
            connection.commit()
        return updated


class OracleHarnessRunStore(OracleRuns, OracleEvents, OracleLeases, OracleOrchestrations):
    """The MemoRizz ``HarnessRunStore`` protocol on Oracle AI Database: the four parts, and recovery."""

    def recover_interrupted(self) -> int:
        """A host that starts finds what its last life left running and says so."""
        recovered = 0
        for run in self.list(limit=10_000):
            if run.status in {HarnessStatus.RUNNING, HarnessStatus.QUEUED}:
                self.update(run.run_id, status=HarnessStatus.INTERRUPTED.value, finished_at=utcnow_iso(),
                            result={"ok": False, "status": HarnessStatus.INTERRUPTED.value, "error_code": "host_restarted",
                                    "error": "The harness host restarted during this run."})
                recovered += 1
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {self.table('LEASES')}")
            connection.commit()
        for orchestration in self.list_orchestrations(limit=10_000):
            if not orchestration.status.terminal:
                self.update_orchestration(orchestration.orchestration_id, status=HarnessStatus.INTERRUPTED.value,
                                          finished_at=utcnow_iso(), error_code="host_restarted",
                                          error="The harness host restarted during this workflow.")
        return recovered

    def close(self) -> None:
        """The pool belongs to the caller."""


class OracleProposals(OracleTables):
    """Proposals: propose, read, list, with expiry applied on every read."""

    COLUMNS = ("proposal_id", "owner_id", "tool_name", "arguments_json", "argument_hash", "policy_reason",
               "checkpoint_json", "status", "created_at", "expires_at", "approver_id", "decision_reason",
               "decided_at", "consumed_at")

    def _proposal(self, row: tuple) -> ApprovalProposal:
        r = dict(zip(self.COLUMNS, row))
        return ApprovalProposal(proposal_id=r["proposal_id"], owner_id=r["owner_id"], tool_name=r["tool_name"],
                                arguments=json.loads(r["arguments_json"]), argument_hash=r["argument_hash"],
                                policy_reason=r["policy_reason"], status=ApprovalStatus(r["status"]),
                                created_at=_when(r["created_at"]), expires_at=_when(r["expires_at"]),
                                checkpoint=json.loads(r["checkpoint_json"] or "{}"), approver_id=r["approver_id"],
                                decision_reason=r["decision_reason"], decided_at=_when(r["decided_at"]),
                                consumed_at=_when(r["consumed_at"]))

    def _expire(self, cursor: Any) -> None:
        cursor.execute(f"UPDATE {self.table('APPROVALS')} SET status = :1 WHERE status IN (:2, :3) AND expires_at <= :4",
                       [ApprovalStatus.EXPIRED.value, ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value,
                        _iso(_now())])

    def _select(self) -> str:
        return f"SELECT {', '.join(self.COLUMNS)} FROM {self.table('APPROVALS')}"

    def propose(self, *, owner_id: str, tool_name: str, arguments: dict, policy_reason: str,
                checkpoint: dict | None = None, ttl_seconds: int = 900) -> ApprovalProposal:
        created = _now()
        expires = created + timedelta(seconds=max(1, min(int(ttl_seconds), 86_400)))
        proposal_id = str(uuid.uuid4())
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {self.table('APPROVALS')} (proposal_id, owner_id, tool_name, arguments_json, "
                           "argument_hash, policy_reason, checkpoint_json, status, created_at, expires_at) "
                           "VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10)",
                           [proposal_id, owner_id.strip(), tool_name.strip(), canonical_arguments(arguments),
                            argument_hash(tool_name.strip(), arguments), policy_reason.strip(),
                            json.dumps(dict(checkpoint or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                            ApprovalStatus.PENDING.value, _iso(created), _iso(expires)])
            connection.commit()
        return self.get(proposal_id)

    def get(self, proposal_id: str) -> ApprovalProposal | None:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            self._expire(cursor)
            connection.commit()
            cursor.execute(f"{self._select()} WHERE proposal_id = :1", [str(proposal_id or "").strip()])
            row = cursor.fetchone()
        return self._proposal(row) if row else None

    def list(self, *, owner_id: str | None = None, status: Any = None, limit: int = 100) -> list[ApprovalProposal]:
        clauses, binds = [], {"limit": max(1, min(int(limit), 1000))}
        if owner_id:
            clauses.append("owner_id = :owner"); binds["owner"] = owner_id
        if status:
            clauses.append("status = :status"); binds["status"] = status.value if isinstance(status, ApprovalStatus) else str(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            self._expire(cursor)
            connection.commit()
            cursor.execute(f"{self._select()}{where} ORDER BY created_at DESC FETCH FIRST :limit ROWS ONLY", binds)
            return [self._proposal(row) for row in cursor.fetchall()]


class OracleDecisions(OracleProposals):
    """Decisions: approve or reject once, consume once, under a row lock."""

    def _decide(self, proposal_id: str, status: ApprovalStatus, *, approver_id: str,
                decision_reason: str | None) -> ApprovalProposal:
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            self._expire(cursor)
            cursor.execute(f"SELECT status FROM {self.table('APPROVALS')} WHERE proposal_id = :1 FOR UPDATE", [proposal_id])
            row = cursor.fetchone()
            if not row:
                connection.rollback()
                raise ApprovalNotFound(f"Unknown approval proposal '{proposal_id}'")
            if ApprovalStatus(row[0]) != ApprovalStatus.PENDING:
                connection.rollback()
                raise ApprovalStateError(f"Approval proposal '{proposal_id}' is {row[0]}, not pending")
            cursor.execute(f"UPDATE {self.table('APPROVALS')} SET status = :1, approver_id = :2, decision_reason = :3, "
                           "decided_at = :4 WHERE proposal_id = :5",
                           [status.value, approver_id.strip(), (decision_reason or "").strip() or None, _iso(_now()), proposal_id])
            connection.commit()
        return self.get(proposal_id)

    def approve(self, proposal_id: str, *, approver_id: str, decision_reason: str | None = None) -> ApprovalProposal:
        return self._decide(proposal_id, ApprovalStatus.APPROVED, approver_id=approver_id, decision_reason=decision_reason)

    def reject(self, proposal_id: str, *, approver_id: str, decision_reason: str | None = None) -> ApprovalProposal:
        return self._decide(proposal_id, ApprovalStatus.REJECTED, approver_id=approver_id, decision_reason=decision_reason)

    def consume(self, proposal_id: str, *, expected_tool_name: str | None = None,
                expected_arguments: dict | None = None) -> ApprovalProposal:
        """An approval is spent exactly once, and only for the call it was given for."""
        with self.pool.acquire() as connection, connection.cursor() as cursor:
            self._expire(cursor)
            cursor.execute(f"{self._select()} WHERE proposal_id = :1 FOR UPDATE", [proposal_id])
            row = cursor.fetchone()
            if not row:
                connection.rollback()
                raise ApprovalNotFound(f"Unknown approval proposal '{proposal_id}'")
            proposal = self._proposal(row)
            if proposal.status != ApprovalStatus.APPROVED:
                connection.rollback()
                raise ApprovalStateError(f"Approval proposal '{proposal_id}' is {proposal.status.value}, not approved")
            if expected_tool_name is not None and proposal.tool_name != str(expected_tool_name).strip():
                connection.rollback()
                raise ApprovalMismatch("Approved tool name does not match the checkpoint")
            if expected_arguments is not None and proposal.argument_hash != argument_hash(proposal.tool_name, expected_arguments):
                connection.rollback()
                raise ApprovalMismatch("Approved arguments do not match the checkpoint")
            cursor.execute(f"UPDATE {self.table('APPROVALS')} SET status = :1, consumed_at = :2 "
                           "WHERE proposal_id = :3 AND status = :4",
                           [ApprovalStatus.CONSUMED.value, _iso(_now()), proposal_id, ApprovalStatus.APPROVED.value])
            if cursor.rowcount != 1:
                connection.rollback()
                raise ApprovalStateError("Approval was already consumed")
            connection.commit()
        return self.get(proposal_id)


class OracleApprovalStore(OracleDecisions):
    """The MemoRizz ``ApprovalStore`` protocol on Oracle AI Database."""

    def close(self) -> None:
        """The pool belongs to the caller."""
