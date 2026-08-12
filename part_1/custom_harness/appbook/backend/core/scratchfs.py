"""Session-scoped scratch files backed by Oracle SecureFile BLOBs.

ScratchFS is deliberately separate from OAMP: plans, drafts and large tool output
are cheap working state.  Only files marked ``promote_on_end`` cross the explicit
session-end trigger and are then consumed into durable OAMP memory.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from backend.config import settings
from backend.core import store


def _content(value: Any) -> bytes:
    if value is None:
        return b""
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


class ScratchFS:
    """A narrow POSIX-like interface scoped to one logical agent session."""

    def __init__(self, session_id: str, mount: str = "/scratch") -> None:
        self.session_id = session_id
        self.mount = mount.rstrip("/")

    def _abs(self, path: str) -> str:
        requested = PurePosixPath("/" + str(path).strip("/"))
        if ".." in requested.parts:
            raise ValueError("Scratch paths cannot escape their session mount")
        clean = "/" + str(requested).lstrip("/")
        return clean if clean == self.mount or clean.startswith(self.mount + "/") else self.mount + clean

    def mkdir(self, path: str) -> None:
        absolute = self._abs(path)
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """MERGE INTO erpa_scratch_files d
                           USING (SELECT :session_id session_id,:path path FROM dual) s
                           ON (d.session_id=s.session_id AND d.path=s.path)
                           WHEN NOT MATCHED THEN INSERT(session_id,path,is_dir)
                             VALUES(s.session_id,s.path,'Y')""",
                        {"session_id": self.session_id, "path": absolute},
                    )
                connection.commit()
            finally:
                connection.close()
            return
        store.initialize()
        with store.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO custom_scratch_files(session_id,path,is_dir,content,promote_on_end,promotion_state,updated_at) "
                "VALUES (?,?,1,?,0,'N',CURRENT_TIMESTAMP)",
                (self.session_id, absolute, b""),
            )

    def write(self, path: str, content: str, *, promote_on_end: bool = False) -> dict[str, Any]:
        absolute, data = self._abs(path), content.encode("utf-8")
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """MERGE INTO erpa_scratch_files d
                           USING (SELECT :session_id session_id,:path path FROM dual) s
                           ON (d.session_id=s.session_id AND d.path=s.path)
                           WHEN MATCHED THEN UPDATE SET content=:content,is_dir='N',promotion_state='N',
                             promote_on_end=:promote,updated_at=SYSTIMESTAMP
                           WHEN NOT MATCHED THEN INSERT(session_id,path,content,is_dir,promote_on_end)
                             VALUES(s.session_id,s.path,:content,'N',:promote)""",
                        {"session_id": self.session_id, "path": absolute, "content": data,
                         "promote": "Y" if promote_on_end else "N"},
                    )
                connection.commit()
            finally:
                connection.close()
        else:
            store.initialize()
            with store.connect() as connection:
                connection.execute(
                    """INSERT INTO custom_scratch_files
                       (session_id,path,is_dir,content,promote_on_end,promotion_state,updated_at)
                       VALUES (?,?,0,?,?,'N',CURRENT_TIMESTAMP)
                       ON CONFLICT(session_id,path) DO UPDATE SET
                         is_dir=0,content=excluded.content,promote_on_end=excluded.promote_on_end,
                         promotion_state='N',updated_at=CURRENT_TIMESTAMP""",
                    (self.session_id, absolute, data, int(promote_on_end)),
                )
        return {"path": absolute, "bytes": len(data), "promote_on_end": promote_on_end}

    def read(self, path: str) -> str:
        absolute = self._abs(path)
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT content FROM erpa_scratch_files WHERE session_id=:1 AND path=:2 AND is_dir='N'",
                        [self.session_id, absolute],
                    )
                    row = cursor.fetchone()
            finally:
                connection.close()
        else:
            store.initialize()
            with store.connect() as connection:
                row = connection.execute(
                    "SELECT content FROM custom_scratch_files WHERE session_id=? AND path=? AND is_dir=0",
                    (self.session_id, absolute),
                ).fetchone()
        if row is None:
            raise FileNotFoundError(absolute)
        return _content(row[0]).decode("utf-8", errors="replace")

    def exists(self, path: str) -> bool:
        absolute = self._abs(path)
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM erpa_scratch_files WHERE session_id=:1 AND path=:2",
                        [self.session_id, absolute],
                    )
                    return cursor.fetchone() is not None
            finally:
                connection.close()
        store.initialize()
        with store.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM custom_scratch_files WHERE session_id=? AND path=?",
                (self.session_id, absolute),
            ).fetchone() is not None

    def append(self, path: str, content: str, *, promote_on_end: bool = False) -> dict[str, Any]:
        prior = self.read(path) if self.exists(path) else ""
        return self.write(path, prior + content, promote_on_end=promote_on_end)

    def list(self, root: str = "/") -> list[str]:
        prefix = self._abs(root).rstrip("/") + "/%"
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT path FROM erpa_scratch_files WHERE session_id=:1 AND path LIKE :2 "
                        "AND is_dir='N' ORDER BY path",
                        [self.session_id, prefix],
                    )
                    return [row[0] for row in cursor.fetchall()]
            finally:
                connection.close()
        store.initialize()
        with store.connect() as connection:
            return [row[0] for row in connection.execute(
                "SELECT path FROM custom_scratch_files WHERE session_id=? AND path LIKE ? AND is_dir=0 ORDER BY path",
                (self.session_id, prefix),
            ).fetchall()]

    def tail(self, path: str, lines: int = 20) -> str:
        return "\n".join(self.read(path).splitlines()[-max(1, lines):])

    def grep(self, pattern: str, root: str = "/") -> list[dict[str, Any]]:
        expression = re.compile(pattern, re.IGNORECASE)
        hits = []
        for path in self.list(root):
            for line_number, line in enumerate(self.read(path).splitlines(), 1):
                if expression.search(line):
                    hits.append({"path": path, "line": line_number, "text": line[:300]})
        return hits


def begin_session(session_id: str, thread_id: str, user_id: str = settings.user_id) -> ScratchFS:
    """Start or resume a logical session and create its standard directories."""
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """MERGE INTO erpa_agent_sessions d
                       USING (SELECT :session_id session_id FROM dual) s ON(d.session_id=s.session_id)
                       WHEN MATCHED THEN UPDATE SET user_id=:user_id,thread_id=:thread_id,
                         status='ACTIVE',ended_at=NULL
                       WHEN NOT MATCHED THEN INSERT(session_id,user_id,thread_id)
                         VALUES(:session_id,:user_id,:thread_id)""",
                    {"session_id": session_id, "user_id": user_id, "thread_id": thread_id},
                )
            connection.commit()
        finally:
            connection.close()
    else:
        store.initialize()
        with store.connect() as connection:
            connection.execute(
                """INSERT INTO custom_agent_sessions(session_id,user_id,thread_id,status,started_at,ended_at)
                   VALUES (?,?,?,'ACTIVE',CURRENT_TIMESTAMP,NULL)
                   ON CONFLICT(session_id) DO UPDATE SET user_id=excluded.user_id,
                     thread_id=excluded.thread_id,status='ACTIVE',ended_at=NULL""",
                (session_id, user_id, thread_id),
            )
    filesystem = ScratchFS(session_id)
    for directory in ("/plans", "/notes", "/tool_out", "/inbox"):
        filesystem.mkdir(directory)
    return filesystem


def stage_session_end(session_id: str) -> int:
    """Transition ACTIVE→ENDED; Oracle's row trigger stages promotable files."""
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE erpa_agent_sessions SET status='ENDED',ended_at=SYSTIMESTAMP "
                    "WHERE session_id=:1 AND status<>'ENDED'",
                    [session_id],
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM erpa_memory_promotion_queue WHERE session_id=:1 AND consumed='N'",
                    [session_id],
                )
                count = int(cursor.fetchone()[0])
            connection.commit()
            return count
        finally:
            connection.close()
    store.initialize()
    with store.connect() as connection:
        connection.execute(
            "UPDATE custom_agent_sessions SET status='ENDED',ended_at=CURRENT_TIMESTAMP "
            "WHERE session_id=? AND status<>'ENDED'",
            (session_id,),
        )
        rows = connection.execute(
            "SELECT path,content FROM custom_scratch_files WHERE session_id=? AND is_dir=0 "
            "AND promote_on_end=1 AND promotion_state='N'",
            (session_id,),
        ).fetchall()
        for row in rows:
            connection.execute(
                "INSERT INTO custom_memory_promotion_queue(session_id,path,chunk,consumed,staged_at) "
                "VALUES (?,?,?,'N',CURRENT_TIMESTAMP)",
                (session_id, row[0], _content(row[1]).decode("utf-8", errors="replace")),
            )
            connection.execute(
                "UPDATE custom_scratch_files SET promotion_state='S' WHERE session_id=? AND path=?",
                (session_id, row[0]),
            )
        return len(rows)


def drain_promotion_queue(limit: int = 500) -> int:
    """Consume staged chunks with OAMP; PL/SQL never attempts to call Python."""
    from backend.core.memory import memory_provider

    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT queue_id,session_id,path,chunk FROM erpa_memory_promotion_queue "
                    "WHERE consumed='N' ORDER BY staged_at FETCH FIRST :1 ROWS ONLY",
                    [limit],
                )
                rows = cursor.fetchall()
            for queue_id, session_id, path, chunk in rows:
                value = chunk.read() if hasattr(chunk, "read") else str(chunk)
                memory_provider.write(
                    "semantic", f"Promoted scratch note {path}: {value}", settings.user_id,
                    {"source": "scratch_promotion", "kind": "fact", "session_id": session_id},
                    ttl_days=settings.oamp_max_ttl_days,
                )
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE erpa_memory_promotion_queue SET consumed='Y',consumed_at=SYSTIMESTAMP WHERE queue_id=:1",
                        [queue_id],
                    )
                    cursor.execute(
                        "UPDATE erpa_scratch_files SET promotion_state='Y' WHERE session_id=:1 AND path=:2",
                        [session_id, path],
                    )
                connection.commit()
            return len(rows)
        finally:
            connection.close()
    store.initialize()
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT queue_id,session_id,path,chunk FROM custom_memory_promotion_queue "
            "WHERE consumed='N' ORDER BY staged_at LIMIT ?",
            (limit,),
        ).fetchall()
    for row in rows:
        memory_provider.write(
            "semantic", f"Promoted scratch note {row['path']}: {row['chunk']}", settings.user_id,
            {"source": "scratch_promotion", "kind": "fact", "session_id": row["session_id"]},
        )
        with store.connect() as connection:
            connection.execute(
                "UPDATE custom_memory_promotion_queue SET consumed='Y',consumed_at=CURRENT_TIMESTAMP WHERE queue_id=?",
                (row["queue_id"],),
            )
            connection.execute(
                "UPDATE custom_scratch_files SET promotion_state='Y' WHERE session_id=? AND path=?",
                (row["session_id"], row["path"]),
            )
    return len(rows)


def end_session(session_id: str) -> dict[str, Any]:
    staged = stage_session_end(session_id)
    promoted = drain_promotion_queue()
    if settings.live:
        from backend.core.memory import memory_provider
        memory_provider.wait_for_extraction()
    return {"session_id": session_id, "status": "ENDED", "staged": staged, "promoted": promoted}


def scratch_status(session_id: str | None = None) -> dict[str, Any]:
    return {
        "implementation": "Oracle SecureFile ScratchFS" if settings.live else "SQLite ScratchFS teaching mirror",
        "session_id": session_id,
        "files": ScratchFS(session_id).list("/") if session_id else [],
        "promotion": "logical session end → Oracle row trigger → queue → OAMP consumer" if settings.live
        else "logical session end → local queue → OAMP-shaped memory provider",
    }
