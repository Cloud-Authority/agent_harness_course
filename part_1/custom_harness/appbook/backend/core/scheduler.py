"""Scheduled morning brief: DBMS_SCHEDULER in production, thread timer locally."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from backend.config import settings
from backend.core import store


class BriefScheduler:
    def __init__(self):
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack
            get_oracle_stack()
        else:
            store.initialize()
        interval = settings.queue_poll_interval if settings.live else settings.schedule_interval
        if interval > 0 and self._timer is None:
            self._timer = threading.Timer(interval, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _tick(self) -> None:
        try:
            if settings.live:
                self.process_queue()
            else:
                self.run_now()
        finally:
            self._timer = None
            self.start()

    def run_now(self) -> dict:
        from backend.core.agent import get_graph
        with self._lock:
            result = get_graph().run("Morning brief.", thread_id="scheduler", bypass_cache=True)
            stamp = datetime.now(timezone.utc).isoformat()
            brief_id = uuid.uuid4().hex
            if settings.live:
                self._persist_live_brief(brief_id, "planner-01", result["answer"])
            else:
                with store.connect() as conn:
                    conn.execute("INSERT INTO custom_briefs VALUES (?,?,?,?,?)",
                                 (brief_id, "planner-01", result["answer"], result["trace"]["trace_id"], stamp))
                    conn.execute("UPDATE custom_schedule SET last_run=?, status='scheduled' WHERE job_name='erpa_morning_brief'", (stamp,))
            return {"brief_id": brief_id, "created_at": stamp, **result}

    @staticmethod
    def _persist_live_brief(brief_id: str, user_id: str, content: str) -> None:
        from backend.core.oracle_live import get_oracle_stack
        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO erpa_briefs (brief_id,user_id,content) VALUES (:1,:2,:3)",
                    [brief_id, user_id, content],
                )
            connection.commit()
        finally:
            connection.close()

    def process_queue(self) -> dict:
        """Claim DBMS_SCHEDULER requests and run them through the standard graph."""
        if not settings.live:
            return {"processed": 0, "mode": "local"}
        from backend.core.agent import get_graph
        from backend.core.oracle_live import get_oracle_stack

        claimed: list[tuple[str, str, str]] = []
        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT request_id,user_id,prompt FROM erpa_brief_queue "
                    "WHERE status='queued' ORDER BY created_at FETCH FIRST 10 ROWS ONLY"
                )
                candidates = cursor.fetchall()
                for request_id, user_id, prompt in candidates:
                    cursor.execute(
                        "UPDATE erpa_brief_queue SET status='processing' "
                        "WHERE request_id=:1 AND status='queued'",
                        [request_id],
                    )
                    if cursor.rowcount == 1:
                        claimed.append((request_id, user_id, prompt))
            connection.commit()
        finally:
            connection.close()

        completed, failed = [], []
        for request_id, user_id, prompt in claimed:
            try:
                result = get_graph().run(prompt, f"scheduled-{request_id}", user_id, bypass_cache=True)
                brief_id = uuid.uuid4().hex
                self._persist_live_brief(brief_id, user_id, result["answer"])
                state, error = "completed", None
                completed.append({"request_id": request_id, "brief_id": brief_id})
            except Exception as exc:
                state, error = "failed", str(exc)[:2000]
                failed.append({"request_id": request_id, "error": error})
            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE erpa_brief_queue SET status=:1,completed_at=CURRENT_TIMESTAMP,error_message=:2 "
                        "WHERE request_id=:3",
                        [state, error, request_id],
                    )
                connection.commit()
            finally:
                connection.close()
        return {"processed": len(claimed), "completed": completed, "failed": failed}

    def status(self) -> dict:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack
            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM erpa_briefs")
                    count = int(cursor.fetchone()[0])
                    cursor.execute(
                        "SELECT state, next_run_date, last_start_date FROM user_scheduler_jobs WHERE job_name='ERPA_MORNING_BRIEF_JOB'"
                    )
                    row = cursor.fetchone()
                    cursor.execute("SELECT status,COUNT(*) FROM erpa_brief_queue GROUP BY status")
                    queue = {status: int(total) for status, total in cursor.fetchall()}
            finally:
                connection.close()
            return {
                "job_name": "ERPA_MORNING_BRIEF_JOB",
                "status": row[0] if row else "not-installed",
                "next_run": str(row[1]) if row else None,
                "last_run": str(row[2]) if row else None,
                "delivery": "in-app",
                "runs_persisted": count,
                "implementation": "Oracle DBMS_SCHEDULER + standard LangGraph worker",
                "queue": queue,
                "poll_interval_seconds": settings.queue_poll_interval,
            }
        store.initialize()
        with store.connect() as conn:
            row = conn.execute("SELECT * FROM custom_schedule WHERE job_name='erpa_morning_brief'").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM custom_briefs").fetchone()[0]
        return {**dict(row), "delivery": "in-app", "runs_persisted": count,
                "implementation": "DBMS_SCHEDULER (live) / background timer (local)", "local_interval_seconds": settings.schedule_interval}


scheduler = BriefScheduler()
