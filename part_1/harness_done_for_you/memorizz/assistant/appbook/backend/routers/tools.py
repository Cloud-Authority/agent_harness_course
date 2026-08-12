"""Chapter 5: direct function/API tools (intentionally no MCP)."""
from fastapi import APIRouter, HTTPException

from backend.core.tools import toolbox
from backend.schemas import ToolReq

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/status")
async def status():
    return {"chapter": "Tools", "ready": True, "transport": "direct API calls", "tools": toolbox.catalog()}


@router.post("/call")
async def call(req: ToolReq):
    try:
        return {"tool": req.name, "result": toolbox.call(req.name, **req.arguments)}
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
