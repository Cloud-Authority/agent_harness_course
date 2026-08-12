"""Chapter 4: inspect and mutate all four memory types."""
from fastapi import APIRouter

from backend.core.agent import get_agent
from backend.schemas import AskReq, MemoryReq

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/status")
async def status():
    values = get_agent().memory.all()
    return {"chapter": "Memory", "ready": True, "counts": {k: len(v) for k, v in values.items()}, "memories": values}


@router.post("/recall")
async def recall(req: AskReq):
    return {"query": req.question, "recalled": get_agent().memory.recall(req.question)}


@router.post("/write")
async def write(req: MemoryReq):
    return get_agent().memory.remember(req.memory_type, req.content, user_id=req.user_id, metadata={"source": "appbook"})
