"""Chapter 3: schema meaning, canonical metrics, guardrails and provenance."""
from fastapi import APIRouter, HTTPException

from backend.core.semantic import semantic_layer
from backend.schemas import AskReq, SqlReq

router = APIRouter(prefix="/api/semantic_layer", tags=["semantic_layer"])


@router.get("/status")
async def status():
    return {"chapter": "Semantic Layer", "ready": True, **semantic_layer.catalog()}


@router.post("/ask")
async def ask(req: AskReq):
    return semantic_layer.ask(req.question)


@router.post("/compare")
async def compare(req: AskReq):
    return semantic_layer.compare(req.question)


@router.post("/sql")
async def sql(req: SqlReq):
    try:
        return semantic_layer.execute_read_only(req.sql)
    except (ValueError, Exception) as exc:
        raise HTTPException(400, str(exc)) from exc
