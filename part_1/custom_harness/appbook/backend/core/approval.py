"""Host-owned approval ledger for concrete side-effect drafts."""
from __future__ import annotations

import json
import uuid
from typing import Any

from backend.config import settings
from backend.core import store


def create_action_draft(action_type: str, payload: dict[str, Any], thread_id: str) -> dict[str, Any]:
    action_id = uuid.uuid4().hex
    serialised = json.dumps(payload, default=str, separators=(",", ":"))
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO erpa_action_audit(action_id,thread_id,action_type,payload,approval_state) "
                    "VALUES (:1,:2,:3,:4,'DRAFTED')",
                    [action_id, thread_id, action_type, serialised],
                )
            connection.commit()
        finally:
            connection.close()
    else:
        store.initialize()
        with store.connect() as connection:
            connection.execute(
                "INSERT INTO custom_action_audit VALUES (?,?,?,?, 'DRAFTED', CURRENT_TIMESTAMP, NULL)",
                (action_id, thread_id, action_type, serialised),
            )
    return {"action_id": action_id, "status": "DRAFTED", "external_mutation": False}


def approve_action(action_id: str) -> dict[str, Any]:
    """Represent the deliberate UI/API action owned by the human host."""
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE erpa_action_audit SET approval_state='APPROVED',approved_at=SYSTIMESTAMP "
                    "WHERE action_id=:1 AND approval_state='DRAFTED'",
                    [action_id],
                )
                changed = cursor.rowcount
            connection.commit()
        finally:
            connection.close()
    else:
        store.initialize()
        with store.connect() as connection:
            cursor = connection.execute(
                "UPDATE custom_action_audit SET approval_state='APPROVED',approved_at=CURRENT_TIMESTAMP "
                "WHERE action_id=? AND approval_state='DRAFTED'",
                (action_id,),
            )
            changed = cursor.rowcount
    return {"action_id": action_id, "status": "APPROVED" if changed else "not_found_or_not_drafted"}


def execute_approved_action(action_id: str) -> dict[str, Any]:
    """Prove the gate without mutating any external system in this workshop."""
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT approval_state FROM erpa_action_audit WHERE action_id=:1", [action_id])
                row = cursor.fetchone()
                if not row or row[0] != "APPROVED":
                    return {"action_id": action_id, "status": "approval_required"}
                cursor.execute(
                    "UPDATE erpa_action_audit SET approval_state='EXECUTED' WHERE action_id=:1",
                    [action_id],
                )
            connection.commit()
        finally:
            connection.close()
    else:
        store.initialize()
        with store.connect() as connection:
            row = connection.execute(
                "SELECT approval_state FROM custom_action_audit WHERE action_id=?", (action_id,),
            ).fetchone()
            if not row or row[0] != "APPROVED":
                return {"action_id": action_id, "status": "approval_required"}
            connection.execute(
                "UPDATE custom_action_audit SET approval_state='EXECUTED' WHERE action_id=?", (action_id,),
            )
    return {
        "action_id": action_id, "status": "EXECUTED",
        "adapter": "demonstration", "external_mutation": False,
    }
