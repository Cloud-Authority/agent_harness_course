"""Chapter 3: persona, provider and toolbox in one MemAgent."""
from fastapi import APIRouter

from backend.core.agent import get_agent
from backend.schemas import ChatReq

router = APIRouter(prefix="/api/the_memagent", tags=["the_memagent"])


@router.get("/status")
async def status():
    agent = get_agent()
    return {"chapter": "The MemAgent", "ready": True, "persona": agent.persona,
            "memory_provider": agent.memory.__class__.__name__, "tools": agent.toolbox.catalog()}


@router.post("/turn")
async def turn(req: ChatReq):
    return get_agent().run(req.message, req.thread_id)
