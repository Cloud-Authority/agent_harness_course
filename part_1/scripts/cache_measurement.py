"""Required cache deliverable: repeat a query and report trace-derived deltas."""
from __future__ import annotations

import json
import sys
from pathlib import Path

APPBOOK = Path(__file__).resolve().parents[1] / "custom_harness" / "appbook"
sys.path.insert(0, str(APPBOOK))

from backend.core.agent import get_graph  # noqa: E402
from backend.core.cache import semantic_cache  # noqa: E402

query = "Why did WarmLayer spike in the UK last week?"
blended_cost_per_million_tokens = 2.00  # illustrative workshop estimate, not a bill
semantic_cache.clear()
cold = get_graph().run(query, "measurement-cold")["trace"]
warm = get_graph().run(query, "measurement-warm")["trace"]
report = {
    "query": query,
    "cold": {"trace_id": cold["trace_id"], "latency_ms": cold["latency_ms"], "tokens": cold["tokens"], "estimated_cost_usd": round(cold["tokens"] / 1_000_000 * blended_cost_per_million_tokens, 6), "cache_hit": cold["cache_hit"], "model_span": any(s["kind"] == "model" for s in cold["spans"])},
    "warm": {"trace_id": warm["trace_id"], "latency_ms": warm["latency_ms"], "tokens": warm["tokens"], "estimated_cost_usd": round(warm["tokens"] / 1_000_000 * blended_cost_per_million_tokens, 6), "cache_hit": warm["cache_hit"], "model_span": any(s["kind"] == "model" for s in warm["spans"])},
    "delta": {"latency_ms": round(cold["latency_ms"] - warm["latency_ms"], 3), "tokens": cold["tokens"] - warm["tokens"], "estimated_cost_usd": round((cold["tokens"] - warm["tokens"]) / 1_000_000 * blended_cost_per_million_tokens, 6)},
    "assertion": "warm trace contains no model span",
    "timing_source": "local comparable trace; LangSmith trace metadata in live mode",
    "cost_assumption": f"illustrative blended ${blended_cost_per_million_tokens:.2f} per million tokens",
}
assert report["cold"]["model_span"] and not report["warm"]["model_span"]
print(json.dumps(report, indent=2))
