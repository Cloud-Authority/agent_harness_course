"""Token normalisation and cost estimates, so four harnesses can share one table.

Each harness reports usage in its own shape. Two differences matter when
comparing them.

* **What "input tokens" includes.** pi and the MemAgent report the whole
  prompt, cached tokens included. Hermes and Claude Code report only the
  tokens that were not served from the prompt cache.
* **Who prices the run.** pi reports a cost. Hermes reports none. MemoRizz
  estimates DeepSeek's. A MemAgent run reports tokens only.

This module reduces every report to the same four counts and prices them with
one dated table, so a row in the comparison means the same thing for every
harness. A reported cost is kept beside the estimate, never replaced by it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

PRICES_AS_OF = "2026-09-25"
PRICE_SOURCE = "Anthropic list prices per million tokens"
# USD per million tokens: uncached input, cache read, cache write (5 minute), output.
PRICES: Dict[str, Dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "cache_read": 0.20, "cache_write": 5.00, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "cache_read": 0.20, "cache_write": 2.50, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "cache_read": 0.10, "cache_write": 1.25, "output": 5.00},
}
# Harnesses whose "input_tokens" already contains the cached tokens.
INPUT_INCLUDES_CACHE = {"pi", "memagent"}


def _count(usage: Dict[str, Any], *names: str) -> int:
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, int(value))
    return 0


def normalise_usage(harness: str, usage: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Reduce one harness's usage report to four comparable counts."""
    raw = dict(usage or {})
    cache_read = _count(raw, "cached_input_tokens", "cache_read_input_tokens", "cached_tokens")
    cache_write = _count(raw, "cache_creation_input_tokens", "cache_write_tokens")
    reported_input = _count(raw, "input_tokens", "prompt_tokens")
    if harness in INPUT_INCLUDES_CACHE:
        uncached = max(0, reported_input - cache_read - cache_write)
    else:
        uncached = reported_input
    output = _count(raw, "output_tokens", "completion_tokens")
    return {"uncached_input_tokens": uncached, "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "prompt_tokens": uncached + cache_read + cache_write,
            "output_tokens": output,
            "total_tokens": uncached + cache_read + cache_write + output,
            "model_calls": _count(raw, "calls")}


def model_key(model: Optional[str]) -> str:
    """The bare model name: a ``provider/model`` value loses its provider."""
    return str(model or "").strip().split("/")[-1].split(":")[0]


def estimate_cost(model: Optional[str], counts: Dict[str, int]) -> Optional[float]:
    """Price normalised counts with the dated table. ``None`` when the model is unpriced."""
    price = PRICES.get(model_key(model))
    if price is None:
        return None
    total = (counts["uncached_input_tokens"] * price["input"]
             + counts["cache_read_tokens"] * price["cache_read"]
             + counts["cache_write_tokens"] * price["cache_write"]
             + counts["output_tokens"] * price["output"])
    return round(total / 1_000_000, 6)


def cost_report(harness: str, model: Optional[str], usage: Optional[Dict[str, Any]],
                reported_cost: Optional[float] = None) -> Dict[str, Any]:
    """Counts, the harness's own cost when it gave one, and the table estimate."""
    counts = normalise_usage(harness, usage)
    estimate = estimate_cost(model, counts)
    if reported_cost is not None:
        basis = f"reported by {harness}"
    elif estimate is not None:
        basis = f"estimated from {PRICE_SOURCE}, {PRICES_AS_OF}"
    else:
        basis = "not available: the model is not in the price table"
    return {**counts, "model": model_key(model) or None, "reported_cost_usd": reported_cost,
            "estimated_cost_usd": estimate,
            "cost_usd": reported_cost if reported_cost is not None else estimate,
            "cost_basis": basis}
