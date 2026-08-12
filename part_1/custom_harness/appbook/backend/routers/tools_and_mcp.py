"""Chapter 6: meaning-retrieved trusted function tools."""
from fastapi import APIRouter, HTTPException

from backend.core.tools import tool_registry
from backend.schemas import QueryReq, ToolReq

router = APIRouter(prefix="/api/tools_and_mcp", tags=["tools_and_mcp"])


@router.get("/status")
async def status():
    return {"chapter": "Trusted Tools & Custom Toolbox", "ready": True,
            "tools": tool_registry.catalog(),
            "authority_boundary": "semantic retrieval controls disclosure; only allowlisted Python callables can execute",
            "generated_code": "E2B only in live mode; no host fallback",
            "missing": {"MCP": "not implemented", "live_search": "governed external-signal ingestion only"}}


@router.post("/retrieve")
async def retrieve(req: QueryReq):
    selected = tool_registry.retrieve(req.query)
    return {"query": req.query, "selected": selected, "all_tool_count": len(tool_registry.catalog()), "context_tool_count": len(selected)}


@router.post("/call")
async def call(req: ToolReq):
    try:
        return {"tool": req.name, "result": tool_registry.call(req.name, **req.arguments)}
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
