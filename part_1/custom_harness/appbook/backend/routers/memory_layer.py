"""Chapter 2: four OAMP memory types, with distinct traceable operations."""
from fastapi import APIRouter

from backend.core.memory import memory_provider
from backend.core.scratchfs import ScratchFS, begin_session, end_session, scratch_status
from backend.core.agent import get_graph
from backend.config import settings
from backend.schemas import AskReq, ChatReq, MemoryReq, MemoryUpdateReq, ScratchWriteReq, SessionReq


def _session_state(session_id: str) -> dict:
    filesystem = ScratchFS(session_id)
    files = []
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack
        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT path,content,promote_on_end,promotion_state,updated_at
                       FROM erpa_scratch_files WHERE session_id=:1 AND is_dir='N' ORDER BY path""",
                    [session_id],
                )
                for path, content, promote, promotion, updated in cursor.fetchall():
                    value = content.read() if hasattr(content, "read") else content
                    if isinstance(value, bytes): value = value.decode("utf-8", errors="replace")
                    files.append({"path": path, "content": value, "promote_on_end": promote == "Y",
                                  "promotion_state": promotion, "updated_at": str(updated)})
                cursor.execute("SELECT status FROM erpa_agent_sessions WHERE session_id=:1", [session_id])
                row = cursor.fetchone()
                status = row[0] if row else "NOT_STARTED"
        finally:
            connection.close()
    else:
        from backend.core import store
        store.initialize()
        with store.connect() as connection:
            rows = connection.execute(
                """SELECT path,content,promote_on_end,promotion_state,updated_at
                   FROM custom_scratch_files WHERE session_id=? AND is_dir=0 ORDER BY path""",
                (session_id,),
            ).fetchall()
            files = [{"path": row["path"], "content": bytes(row["content"] or b"").decode("utf-8", errors="replace"),
                      "promote_on_end": bool(row["promote_on_end"]), "promotion_state": row["promotion_state"],
                      "updated_at": row["updated_at"]} for row in rows]
            row = connection.execute("SELECT status FROM custom_agent_sessions WHERE session_id=?", (session_id,)).fetchone()
            status = row[0] if row else "NOT_STARTED"
    memories = memory_provider.list(settings.user_id)
    return {
        "session_id": session_id,
        "status": status,
        "memories": {kind: items[-12:] for kind, items in memories.items()},
        "memory_counts": {kind: len(items) for kind, items in memories.items()},
        "scratch_files": files,
    }

router = APIRouter(prefix="/api/memory_layer", tags=["memory_layer"])


@router.get("/status")
async def status():
    return {"chapter": "Memory Layer", **memory_provider.status(),
            "working_memory": scratch_status(),
            "tracing": ["memory.read.oamp", "memory.write.oamp"]}


@router.post("/recall")
async def recall(req: AskReq):
    return {"query": req.question, "recalled": memory_provider.recall(req.question, thread_id=req.thread_id),
            "context_card": memory_provider.context_card(req.thread_id)}


@router.post("/chat")
async def chat(req: ChatReq):
    session_id = req.session_id or "memory-lab-session"
    filesystem = begin_session(session_id, req.thread_id)
    filesystem.write("/plans/current.md", f"# Current objective\n{req.message}\n")
    before = {kind: len(items) for kind, items in memory_provider.list(settings.user_id).items()}
    if settings.live:
        result = get_graph().run(req.message, req.thread_id, session_id=session_id)
    else:
        result = get_graph().run(req.message, req.thread_id)
    filesystem.append(
        "/notes/observations.md",
        f"\n## User\n{req.message}\n\n## ERPA\n{result['answer']}\n",
        promote_on_end=True,
    )
    state = _session_state(session_id)
    state["memory_writes_this_turn"] = {
        kind: state["memory_counts"][kind] - before.get(kind, 0) for kind in state["memory_counts"]
    }
    return {**result, "session": state}


@router.post("/session/start")
async def start_session(req: SessionReq):
    begin_session(req.session_id, req.thread_id, req.user_id)
    return _session_state(req.session_id)


@router.get("/session/{session_id}")
async def session_state(session_id: str):
    return _session_state(session_id)


@router.post("/write")
async def write(req: MemoryReq):
    return memory_provider.write(req.memory_type, req.content, req.user_id, {"source": "appbook"},
                                 thread_id=req.thread_id, ttl_days=req.ttl_days)


@router.patch("/{memory_id}")
async def update(memory_id: str, req: MemoryUpdateReq):
    return {"memory_id": memory_provider.update(memory_id, req.content, ttl_days=req.ttl_days)}


@router.delete("/{memory_id}")
async def delete(memory_id: str):
    return {"memory_id": memory_id, "deleted": memory_provider.delete(memory_id)}


@router.post("/extraction/wait")
async def wait_for_extraction():
    memory_provider.wait_for_extraction()
    return {"ready": True, "background_extraction": "drained"}


@router.post("/scratch/write")
async def scratch_write(req: ScratchWriteReq):
    filesystem = begin_session(req.session_id, req.thread_id)
    return filesystem.write(req.path, req.content, promote_on_end=req.promote_on_end)


@router.post("/session/end")
async def finish_session(req: SessionReq):
    begin_session(req.session_id, req.thread_id, req.user_id)
    return end_session(req.session_id)
