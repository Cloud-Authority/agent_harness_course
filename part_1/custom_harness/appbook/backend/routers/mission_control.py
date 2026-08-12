"""Chapter 9: brief, chat, live context, trace, scheduler and persisted assets."""
from fastapi import APIRouter, HTTPException, Response

from backend.core import store
from backend.core.agent import get_graph
from backend.core.scheduler import scheduler
from backend.core.approval import approve_action, create_action_draft, execute_approved_action
from backend.core.scratchfs import end_session
from backend.config import settings
from backend.schemas import ActionDraftReq, BriefReq, ChatReq

router = APIRouter(prefix="/api/mission_control", tags=["mission_control"])


@router.get("/status")
async def status():
    return {"chapter": "Mission Control", "ready": True, "store": store.status(),
            "scheduler": scheduler.status(), "latest_trace": store.latest_trace()}


@router.post("/chat")
async def chat(req: ChatReq):
    if settings.live:
        return get_graph().run(req.message, req.thread_id, session_id=req.session_id)
    return get_graph().run(req.message, req.thread_id)


@router.post("/brief")
async def brief(req: BriefReq):
    return get_graph().run("Morning brief.", "mission-brief", req.user_id, bypass_cache=True)


@router.post("/schedule/run-now")
async def run_now():
    return scheduler.run_now()


@router.post("/sessions/{session_id}/end")
async def finish_session(session_id: str):
    return end_session(session_id)


@router.post("/actions/draft")
async def draft_action(req: ActionDraftReq):
    return create_action_draft(req.action_type, req.payload, req.thread_id)


@router.post("/actions/{action_id}/approve")
async def approve(action_id: str):
    return approve_action(action_id)


@router.post("/actions/{action_id}/execute")
async def execute(action_id: str):
    return execute_approved_action(action_id)


@router.get("/trace")
async def trace():
    return store.latest_trace() or {"message": "No turn has run yet"}


@router.get("/files/{file_id}")
async def file(file_id: str):
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack
        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT mime_type,content FROM erpa_file_storage WHERE file_id=:1", [file_id])
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            raise HTTPException(404, "file pointer not found")
        content = row[1].read() if hasattr(row[1], "read") else row[1]
        return Response(content, media_type=row[0])
    with store.connect() as conn:
        row = conn.execute("SELECT mime_type,content FROM custom_file_storage WHERE file_id=?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file pointer not found")
    return Response(row["content"], media_type=row["mime_type"])
