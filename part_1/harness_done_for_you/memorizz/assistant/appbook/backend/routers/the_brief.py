"""Chapter 6: run the personalised morning brief and inspect suppression."""
import json

from fastapi import APIRouter

from backend.core.agent import get_agent
from backend.core.sse import sse_response
from backend.schemas import BriefReq

router = APIRouter(prefix="/api/the_brief", tags=["the_brief"])


@router.get("/status")
async def status():
    return {"chapter": "The Brief", "ready": True, "prompt": "Morning brief.",
            "proof": ["3 new restock items", "Berlin ThermaCore suppressed", "stored format applied"]}


@router.post("/run")
async def run(req: BriefReq):
    return get_agent().run("Morning brief.", thread_id="brief-thread", user_id=req.user_id)


@router.get("/stream")
async def stream():
    async def events():
        yield {"event": "node", "data": json.dumps({"node": "recall", "status": "running"})}
        result = get_agent().run("Morning brief.", thread_id="brief-stream")
        yield {"event": "result", "data": json.dumps(result)}
    return sse_response(events())
