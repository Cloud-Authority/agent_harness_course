"""Chapter 4: compare retrieval rankings and grounded Claude answers."""
from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.core.retriever import DEMONSTRATION_QUERY, compare_responses
from backend.schemas import QueryReq

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


@router.get("/status")
async def status():
    return {"chapter": "Retrieval", "ready": True, "methods": ["keyword", "vector", "hybrid", "rerank"],
            "sample_query": DEMONSTRATION_QUERY,
            "experiment": "one real corpus, four independent rankings, four context-conditioned Claude answers",
            "answer_generation": {"provider": "Anthropic", "model": settings.anthropic_model,
                                  "thinking": settings.anthropic_thinking,
                                  "configured": bool(settings.anthropic_api_key)}}


@router.post("/compare")
async def run(req: QueryReq):
    try:
        return await compare_responses(req.query)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
