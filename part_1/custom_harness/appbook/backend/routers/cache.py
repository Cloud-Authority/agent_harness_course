"""Chapter 8: boundary-cache latency, token and cost measurement."""
import time
from fastapi import APIRouter

from backend.core.agent import get_graph
from backend.core.cache import semantic_cache
from backend.schemas import QueryReq
from backend.config import settings

router = APIRouter(prefix="/api/cache", tags=["cache"])


@router.get("/status")
async def status():
    return {"chapter": "Cache", "ready": True, **semantic_cache.status(),
            "proof": "A hit returns before assemble_context, so its trace contains no model span."}


@router.post("/clear")
async def clear():
    return {"cleared": semantic_cache.clear()}


@router.post("/measure")
async def measure(req: QueryReq):
    semantic_cache.clear()
    cold = get_graph().run(req.query, "cache-cold")
    warm = get_graph().run(req.query, "cache-warm")
    cold_tokens, warm_tokens = cold["trace"]["tokens"], warm["trace"]["tokens"]
    rate_per_million = 2.0
    return {"query": req.query,
            "cold": {"latency_ms": cold["trace"]["latency_ms"], "tokens": cold_tokens, "model_span": any(s["kind"] == "model" for s in cold["trace"]["spans"]), "trace_id": cold["trace"]["trace_id"]},
            "warm": {"latency_ms": warm["trace"]["latency_ms"], "tokens": warm_tokens, "model_span": any(s["kind"] == "model" for s in warm["trace"]["spans"]), "trace_id": warm["trace"]["trace_id"]},
            "delta": {"latency_ms": round(cold["trace"]["latency_ms"] - warm["trace"]["latency_ms"], 3),
                      "tokens": cold_tokens - warm_tokens, "estimated_cost_usd": round((cold_tokens - warm_tokens) / 1_000_000 * rate_per_million, 6)},
            "assumption": f"Illustrative blended ${rate_per_million:.2f}/1M-token rate; use Anthropic usage and LangSmith billing metadata in live mode.",
            "embedding": "Oracle in-database ALL_MINILM_L12_V2 (live)",
            "prompt_caching": "documented future stable-prefix optimisation; not enabled"}


@router.post("/compare")
async def compare(req: QueryReq):
    """Run the same question through an uncached and cache-enabled conversation."""
    semantic_cache.clear()
    uncached_started = time.perf_counter()
    uncached = get_graph().run(req.query, "cache-disabled", bypass_cache=True)
    uncached_wall = round((time.perf_counter() - uncached_started) * 1000, 3)

    # Isolate the comparison, prime once, then measure the semantic hit.
    semantic_cache.clear()
    get_graph().run(req.query, "cache-prime", bypass_cache=True)
    cached_started = time.perf_counter()
    cached = get_graph().run(req.query, "cache-enabled")
    cached_wall = round((time.perf_counter() - cached_started) * 1000, 3)
    return {
        "query": req.query,
        "without_cache": {"answer": uncached["answer"], "elapsed_ms": uncached_wall,
                          "tokens": uncached["trace"]["tokens"], "trace": uncached["trace"]},
        "with_semantic_cache": {"answer": cached["answer"], "elapsed_ms": cached_wall,
                                "tokens": cached["trace"]["tokens"], "trace": cached["trace"],
                                "cache_hit": cached["trace"]["cache_hit"]},
        "delta_ms": round(uncached_wall - cached_wall, 3),
        "implementation": "OracleSemanticCache" if settings.live else "SQLite semantic-cache mirror",
    }
