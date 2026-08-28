"""Oracle AI Database persistence for MemoRizz MetaHarness runs and approvals.

MemoRizz accepts any objects that implement its run-store and approval-store
interfaces.  The published wheel includes a local store; this course uses the
Oracle implementations below so memory, execution evidence, and approval state
share one production database.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import oracledb
from memorizz.approval import (
    ApprovalMismatch,
    ApprovalNotFound,
    ApprovalProposal,
    ApprovalStateError,
    ApprovalStatus,
    argument_hash,
    canonical_arguments,
)
from memorizz.metaharness import HarnessEvent, HarnessRun, HarnessStatus
from memorizz.metaharness.models import utcnow_iso


_PREFIX = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _lob_text(value: Any) -> str:
    loaded = value.read() if hasattr(value, "read") else value
    # python-oracledb may decode a CLOB carrying an `IS JSON` constraint into a
    # Python object. Normalize both that representation and an ordinary LOB to
    # the same JSON text before the store models consume it.
    if isinstance(loaded, (dict, list)):
        return json.dumps(loaded, ensure_ascii=False, default=str)
    if isinstance(loaded, (bytes, bytearray)):
        return bytes(loaded).decode("utf-8")
    return str(loaded or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _oracle_error_code(exc: BaseException) -> Optional[int]:
    detail = exc.args[0] if getattr(exc, "args", None) else None
    return int(detail.code) if getattr(detail, "code", None) is not None else None


def _create_once(pool: Any, statement: str) -> None:
    """Execute idempotent course DDL and ignore only name-already-exists."""

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(statement)
            except oracledb.DatabaseError as exc:
                if _oracle_error_code(exc) != 955:
                    raise


class OracleHarnessRunStore:
    """Transactional run, event, and workspace-lease state in Oracle."""

    def __init__(self, pool: Any, *, prefix: str = "MH") -> None:
        normalized = str(prefix).strip().upper()
        if not _PREFIX.fullmatch(normalized):
            raise ValueError("Oracle table prefix must be a short unquoted identifier")
        self.pool = pool
        self.prefix = normalized
        self.runs_table = f"{normalized}_RUNS"
        self.events_table = f"{normalized}_EVENTS"
        self.leases_table = f"{normalized}_WORKSPACE_LEASES"
        self._setup()

    def _setup(self) -> None:
        _create_once(
            self.pool,
            f"""CREATE TABLE {self.runs_table} (
                run_id VARCHAR2(64) PRIMARY KEY,
                status VARCHAR2(40) NOT NULL,
                harness VARCHAR2(160),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                payload CLOB NOT NULL CHECK (payload IS JSON)
            )""",
        )
        _create_once(
            self.pool,
            f"CREATE INDEX {self.prefix}_RUN_STATUS_IX "
            f"ON {self.runs_table}(status, updated_at)",
        )
        _create_once(
            self.pool,
            f"""CREATE TABLE {self.events_table} (
                run_id VARCHAR2(64) NOT NULL,
                sequence NUMBER(12) NOT NULL,
                occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
                event_type VARCHAR2(40) NOT NULL,
                payload CLOB NOT NULL CHECK (payload IS JSON),
                CONSTRAINT {self.prefix}_EVENT_PK PRIMARY KEY (run_id, sequence),
                CONSTRAINT {self.prefix}_EVENT_RUN_FK FOREIGN KEY (run_id)
                    REFERENCES {self.runs_table}(run_id) ON DELETE CASCADE
            )""",
        )
        _create_once(
            self.pool,
            f"""CREATE TABLE {self.leases_table} (
                workspace_key VARCHAR2(64) PRIMARY KEY,
                workspace_path VARCHAR2(2048) NOT NULL,
                run_id VARCHAR2(64) NOT NULL,
                acquired_at TIMESTAMP WITH TIME ZONE NOT NULL,
                CONSTRAINT {self.prefix}_LEASE_RUN_FK FOREIGN KEY (run_id)
                    REFERENCES {self.runs_table}(run_id) ON DELETE CASCADE
            )""",
        )

    @staticmethod
    def _decode(value: Any) -> HarnessRun:
        return HarnessRun(**json.loads(_lob_text(value)))

    def create(self, run: HarnessRun) -> HarnessRun:
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""INSERT INTO {self.runs_table}
                        (run_id, status, harness, created_at, updated_at, payload)
                        VALUES (:run_id, :status, :harness, :created_at, :updated_at, :payload)""",
                    {
                        "run_id": run.run_id,
                        "status": run.status.value,
                        "harness": run.harness,
                        "created_at": _as_datetime(run.created_at),
                        "updated_at": _as_datetime(run.updated_at),
                        "payload": _json(run.to_dict()),
                    },
                )
            connection.commit()
        return run

    def get(self, run_id: str) -> Optional[HarnessRun]:
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT payload FROM {self.runs_table} WHERE run_id=:run_id",
                    {"run_id": str(run_id)},
                )
                row = cursor.fetchone()
                return self._decode(row[0]) if row else None

    def list(
        self, *, limit: int = 100, status: Optional[str] = None
    ) -> list[HarnessRun]:
        bounded = max(1, min(int(limit), 10_000))
        where = " WHERE status=:status" if status else ""
        parameters = {"status": str(status)} if status else {}
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT payload FROM {self.runs_table}{where} "
                    f"ORDER BY updated_at DESC FETCH FIRST {bounded} ROWS ONLY",
                    parameters,
                )
                rows = cursor.fetchall()
                return [self._decode(row[0]) for row in rows]

    def update(self, run_id: str, **changes: Any) -> HarnessRun:
        with self.pool.acquire() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT payload FROM {self.runs_table} "
                        "WHERE run_id=:run_id FOR UPDATE",
                        {"run_id": str(run_id)},
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise KeyError(f"Unknown harness run: {run_id}")
                    payload = self._decode(row[0]).to_dict()
                    payload.update(changes)
                    payload["updated_at"] = utcnow_iso()
                    updated = HarnessRun(**payload)
                    cursor.execute(
                        f"""UPDATE {self.runs_table}
                            SET status=:status, harness=:harness,
                                updated_at=:updated_at, payload=:payload
                            WHERE run_id=:run_id""",
                        {
                            "status": updated.status.value,
                            "harness": updated.harness,
                            "updated_at": _as_datetime(updated.updated_at),
                            "payload": _json(updated.to_dict()),
                            "run_id": updated.run_id,
                        },
                    )
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise

    def append_event(self, event: HarnessEvent) -> HarnessEvent:
        with self.pool.acquire() as connection:
            try:
                with connection.cursor() as cursor:
                    # Lock the parent row so independent app workers serialize
                    # sequence allocation for this run.
                    cursor.execute(
                        f"SELECT run_id FROM {self.runs_table} "
                        "WHERE run_id=:run_id FOR UPDATE",
                        {"run_id": event.run_id},
                    )
                    if cursor.fetchone() is None:
                        raise KeyError(f"Unknown harness run: {event.run_id}")
                    if event.sequence is None:
                        cursor.execute(
                            f"SELECT COALESCE(MAX(sequence), 0) FROM {self.events_table} "
                            "WHERE run_id=:run_id",
                            {"run_id": event.run_id},
                        )
                        event.sequence = int(cursor.fetchone()[0] or 0) + 1
                    cursor.execute(
                        f"""INSERT INTO {self.events_table}
                            (run_id, sequence, occurred_at, event_type, payload)
                            VALUES (:run_id, :sequence, :occurred_at, :event_type, :payload)""",
                        {
                            "run_id": event.run_id,
                            "sequence": event.sequence,
                            "occurred_at": _as_datetime(event.timestamp),
                            "event_type": event.type.value,
                            "payload": _json(event.to_dict()),
                        },
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return event

    def events(
        self, run_id: str, *, after: int = 0, limit: int = 1000
    ) -> list[HarnessEvent]:
        bounded = max(1, min(int(limit), 10_000))
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT payload FROM {self.events_table} "
                    "WHERE run_id=:run_id AND sequence>:after "
                    f"ORDER BY sequence FETCH FIRST {bounded} ROWS ONLY",
                    {"run_id": str(run_id), "after": max(0, int(after))},
                )
                rows = cursor.fetchall()
                return [
                    HarnessEvent(**json.loads(_lob_text(row[0]))) for row in rows
                ]

    def acquire_workspace(self, workspace: str, run_id: str) -> bool:
        path = str(workspace)
        key = hashlib.sha256(path.encode("utf-8")).hexdigest()
        with self.pool.acquire() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""INSERT INTO {self.leases_table}
                            (workspace_key, workspace_path, run_id, acquired_at)
                            VALUES (:workspace_key, :workspace_path, :run_id, :acquired_at)""",
                        {
                            "workspace_key": key,
                            "workspace_path": path,
                            "run_id": str(run_id),
                            "acquired_at": _utcnow(),
                        },
                    )
                connection.commit()
                return True
            except oracledb.IntegrityError:
                connection.rollback()
                return False

    def release_workspace(self, workspace: str, run_id: str) -> None:
        key = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {self.leases_table} "
                    "WHERE workspace_key=:workspace_key AND run_id=:run_id",
                    {"workspace_key": key, "run_id": str(run_id)},
                )
            connection.commit()

    def recover_interrupted(self) -> int:
        recovered = 0
        for run in self.list(limit=10_000):
            if run.status in {HarnessStatus.QUEUED, HarnessStatus.RUNNING}:
                self.update(
                    run.run_id,
                    status=HarnessStatus.INTERRUPTED.value,
                    finished_at=utcnow_iso(),
                    result={
                        "ok": False,
                        "status": HarnessStatus.INTERRUPTED.value,
                        "error_code": "host_restarted",
                        "error": "The harness host restarted during this run.",
                    },
                )
                recovered += 1
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {self.leases_table}")
            connection.commit()
        return recovered

    def close(self) -> None:
        """The MemoRizz OracleProvider owns the shared connection pool."""


class OracleApprovalStore:
    """Atomic, single-use approval state in Oracle AI Database."""

    def __init__(self, pool: Any, *, prefix: str = "MH") -> None:
        normalized = str(prefix).strip().upper()
        if not _PREFIX.fullmatch(normalized):
            raise ValueError("Oracle table prefix must be a short unquoted identifier")
        self.pool = pool
        self.prefix = normalized
        self.table = f"{normalized}_APPROVALS"
        self._setup()

    def _setup(self) -> None:
        _create_once(
            self.pool,
            f"""CREATE TABLE {self.table} (
                proposal_id VARCHAR2(64) PRIMARY KEY,
                owner_id VARCHAR2(200) NOT NULL,
                tool_name VARCHAR2(300) NOT NULL,
                arguments_json CLOB NOT NULL CHECK (arguments_json IS JSON),
                argument_hash VARCHAR2(64) NOT NULL,
                policy_reason CLOB NOT NULL,
                checkpoint_json CLOB NOT NULL CHECK (checkpoint_json IS JSON),
                status VARCHAR2(32) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                approver_id VARCHAR2(200),
                decision_reason CLOB,
                decided_at TIMESTAMP WITH TIME ZONE,
                consumed_at TIMESTAMP WITH TIME ZONE
            )""",
        )
        _create_once(
            self.pool,
            f"CREATE INDEX {self.prefix}_APP_OWNER_IX "
            f"ON {self.table}(owner_id, status, created_at)",
        )

    @staticmethod
    def _required_text(value: str, label: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{label} cannot be empty")
        return normalized

    @staticmethod
    def _proposal(row: tuple[Any, ...]) -> ApprovalProposal:
        return ApprovalProposal(
            proposal_id=str(row[0]),
            owner_id=str(row[1]),
            tool_name=str(row[2]),
            arguments=json.loads(_lob_text(row[3])),
            argument_hash=str(row[4]),
            policy_reason=_lob_text(row[5]),
            checkpoint=json.loads(_lob_text(row[6]) or "{}"),
            status=ApprovalStatus(str(row[7])),
            created_at=_as_datetime(row[8]) or _utcnow(),
            expires_at=_as_datetime(row[9]) or _utcnow(),
            approver_id=str(row[10]) if row[10] is not None else None,
            decision_reason=_lob_text(row[11]) if row[11] is not None else None,
            decided_at=_as_datetime(row[12]),
            consumed_at=_as_datetime(row[13]),
        )

    @staticmethod
    def _expire(cursor: Any, table: str) -> None:
        cursor.execute(
            f"""UPDATE {table} SET status=:expired
                WHERE status IN (:pending, :approved) AND expires_at <= SYSTIMESTAMP""",
            {
                "expired": ApprovalStatus.EXPIRED.value,
                "pending": ApprovalStatus.PENDING.value,
                "approved": ApprovalStatus.APPROVED.value,
            },
        )

    def _select(self) -> str:
        return (
            "proposal_id, owner_id, tool_name, arguments_json, argument_hash, "
            "policy_reason, checkpoint_json, status, created_at, expires_at, "
            "approver_id, decision_reason, decided_at, consumed_at"
        )

    def propose(
        self,
        *,
        owner_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        policy_reason: str,
        checkpoint: Optional[dict[str, Any]] = None,
        ttl_seconds: int = 900,
    ) -> ApprovalProposal:
        owner = self._required_text(owner_id, "Approval owner_id")
        tool = self._required_text(tool_name, "Approval tool_name")
        reason = self._required_text(policy_reason, "Approval policy_reason")
        arguments_json = canonical_arguments(arguments)
        checkpoint_json = _json(dict(checkpoint or {}))
        created = _utcnow()
        expires = created + timedelta(seconds=max(1, min(int(ttl_seconds), 86_400)))
        proposal_id = str(uuid.uuid4())
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""INSERT INTO {self.table} (
                        proposal_id, owner_id, tool_name, arguments_json,
                        argument_hash, policy_reason, checkpoint_json, status,
                        created_at, expires_at
                    ) VALUES (
                        :proposal_id, :owner_id, :tool_name, :arguments_json,
                        :argument_hash, :policy_reason, :checkpoint_json, :status,
                        :created_at, :expires_at
                    )""",
                    {
                        "proposal_id": proposal_id,
                        "owner_id": owner,
                        "tool_name": tool,
                        "arguments_json": arguments_json,
                        "argument_hash": argument_hash(tool, arguments),
                        "policy_reason": reason,
                        "checkpoint_json": checkpoint_json,
                        "status": ApprovalStatus.PENDING.value,
                        "created_at": created,
                        "expires_at": expires,
                    },
                )
            connection.commit()
        proposal = self.get(proposal_id)
        if proposal is None:
            raise RuntimeError("Oracle did not return the saved approval proposal")
        return proposal

    def get(self, proposal_id: str) -> Optional[ApprovalProposal]:
        normalized = str(proposal_id or "").strip()
        if not normalized:
            return None
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                self._expire(cursor, self.table)
                cursor.execute(
                    f"SELECT {self._select()} FROM {self.table} "
                    "WHERE proposal_id=:proposal_id",
                    {"proposal_id": normalized},
                )
                row = cursor.fetchone()
                proposal = self._proposal(row) if row else None
            connection.commit()
        return proposal

    def list(
        self,
        *,
        owner_id: Optional[str] = None,
        status: Optional[ApprovalStatus | str] = None,
        limit: int = 100,
    ) -> list[ApprovalProposal]:
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        if owner_id is not None:
            clauses.append("owner_id=:owner_id")
            parameters["owner_id"] = str(owner_id)
        if status is not None:
            clauses.append("status=:status")
            parameters["status"] = ApprovalStatus(
                str(getattr(status, "value", status))
            ).value
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        bounded = max(1, min(int(limit), 500))
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                self._expire(cursor, self.table)
                cursor.execute(
                    f"SELECT {self._select()} FROM {self.table}{where} "
                    f"ORDER BY created_at DESC FETCH FIRST {bounded} ROWS ONLY",
                    parameters,
                )
                rows = cursor.fetchall()
                proposals = [self._proposal(row) for row in rows]
            connection.commit()
        return proposals

    def _decide(
        self,
        proposal_id: str,
        new_status: ApprovalStatus,
        *,
        approver_id: str,
        decision_reason: Optional[str],
    ) -> ApprovalProposal:
        approver = self._required_text(approver_id, "Approver identity")
        with self.pool.acquire() as connection:
            try:
                with connection.cursor() as cursor:
                    self._expire(cursor, self.table)
                    cursor.execute(
                        f"SELECT status FROM {self.table} "
                        "WHERE proposal_id=:proposal_id FOR UPDATE",
                        {"proposal_id": str(proposal_id)},
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ApprovalNotFound(
                            f"Unknown approval proposal '{proposal_id}'"
                        )
                    current = ApprovalStatus(str(row[0]))
                    if current is not ApprovalStatus.PENDING:
                        raise ApprovalStateError(
                            f"Approval proposal '{proposal_id}' is {current.value}, not pending"
                        )
                    cursor.execute(
                        f"""UPDATE {self.table}
                            SET status=:status, approver_id=:approver_id,
                                decision_reason=:decision_reason, decided_at=:decided_at
                            WHERE proposal_id=:proposal_id AND status=:pending""",
                        {
                            "status": new_status.value,
                            "approver_id": approver,
                            "decision_reason": (
                                str(decision_reason).strip() if decision_reason else None
                            ),
                            "decided_at": _utcnow(),
                            "proposal_id": str(proposal_id),
                            "pending": ApprovalStatus.PENDING.value,
                        },
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        proposal = self.get(proposal_id)
        if proposal is None:
            raise ApprovalNotFound(f"Unknown approval proposal '{proposal_id}'")
        return proposal

    def approve(
        self,
        proposal_id: str,
        *,
        approver_id: str,
        decision_reason: Optional[str] = None,
    ) -> ApprovalProposal:
        return self._decide(
            proposal_id,
            ApprovalStatus.APPROVED,
            approver_id=approver_id,
            decision_reason=decision_reason,
        )

    def reject(
        self,
        proposal_id: str,
        *,
        approver_id: str,
        decision_reason: Optional[str] = None,
    ) -> ApprovalProposal:
        return self._decide(
            proposal_id,
            ApprovalStatus.REJECTED,
            approver_id=approver_id,
            decision_reason=decision_reason,
        )

    def consume(
        self,
        proposal_id: str,
        *,
        expected_tool_name: Optional[str] = None,
        expected_arguments: Optional[dict[str, Any]] = None,
    ) -> ApprovalProposal:
        with self.pool.acquire() as connection:
            try:
                with connection.cursor() as cursor:
                    self._expire(cursor, self.table)
                    cursor.execute(
                        f"SELECT {self._select()} FROM {self.table} "
                        "WHERE proposal_id=:proposal_id FOR UPDATE",
                        {"proposal_id": str(proposal_id)},
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ApprovalNotFound(
                            f"Unknown approval proposal '{proposal_id}'"
                        )
                    proposal = self._proposal(row)
                    if proposal.status is not ApprovalStatus.APPROVED:
                        raise ApprovalStateError(
                            f"Approval proposal '{proposal_id}' is "
                            f"{proposal.status.value}, not approved"
                        )
                    if (
                        expected_tool_name is not None
                        and proposal.tool_name != str(expected_tool_name).strip()
                    ):
                        raise ApprovalMismatch(
                            "Approved tool name does not match the saved request"
                        )
                    if expected_arguments is not None and proposal.argument_hash != argument_hash(
                        proposal.tool_name, expected_arguments
                    ):
                        raise ApprovalMismatch(
                            "Approved arguments do not match the saved request"
                        )
                    cursor.execute(
                        f"""UPDATE {self.table}
                            SET status=:consumed, consumed_at=:consumed_at
                            WHERE proposal_id=:proposal_id AND status=:approved""",
                        {
                            "consumed": ApprovalStatus.CONSUMED.value,
                            "consumed_at": _utcnow(),
                            "proposal_id": str(proposal_id),
                            "approved": ApprovalStatus.APPROVED.value,
                        },
                    )
                    if cursor.rowcount != 1:
                        raise ApprovalStateError("Approval was already consumed")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        consumed = self.get(proposal_id)
        if consumed is None:
            raise ApprovalNotFound(f"Unknown approval proposal '{proposal_id}'")
        return consumed

    def close(self) -> None:
        """The MemoRizz OracleProvider owns the shared connection pool."""


__all__ = ["OracleApprovalStore", "OracleHarnessRunStore"]
