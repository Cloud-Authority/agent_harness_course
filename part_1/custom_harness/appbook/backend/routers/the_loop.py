"""Chapter 7: the bounded tool loop and comparable trace."""
import json

from fastapi import APIRouter, Query

from backend.core.agent import get_graph
from backend.core.sse import sse_response
from backend.schemas import ChatReq

router = APIRouter(prefix="/api/the_loop", tags=["the_loop"])


@router.get("/status")
async def status():
    return {"chapter": "The Loop", "ready": True, **get_graph().graph,
            "memory_spans": ["memory.read", "memory.write.preference", "memory.write.working"]}


@router.post("/turn")
async def turn(req: ChatReq):
    return get_graph().run(req.message, req.thread_id)


@router.get("/stream")
async def stream(message: str = Query("Morning brief."), thread_id: str = Query("stream-thread")):
    async def events():
        for node in ("boundary_cache", "assemble_context", "call_model", "dispatch_tools", "finalize", "persist"):
            yield {"event": "node", "data": json.dumps({"node": node, "status": "queued"})}
        result = get_graph().run(message, thread_id)
        yield {"event": "result", "data": json.dumps(result)}
    return sse_response(events())
