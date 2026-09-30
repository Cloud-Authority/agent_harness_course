"""Settings, the model client and the search client."""
from __future__ import annotations

import os
from dataclasses import dataclass

from anthropic import Anthropic
from tavily import TavilyClient


@dataclass(frozen=True)
class TripConfig:
    model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    agent_id: str = "trip-booking-harness"
    tenant_id: str = "ppa-advanced"
    memory_store_id: str = "TRIPMEM"
    currency: str = "GBP"                  # the traveller's currency; prices are converted to it
    rates_to_gbp: tuple = (("GBP", 1.0), ("EUR", 0.86), ("USD", 0.79))   # indicative, for planning only
    search_results: int = 8                # web results read for each search
    max_replans: int = 2                   # how often the traveller may ask for changes
    max_booking_attempts: int = 3          # how often a failed component is re-planned
    crash_after: str = os.getenv("TRIP_CRASH_AFTER", "")   # a node name: the process exits after it, for the resume lesson


CFG = TripConfig()
_clients: dict[str, object] = {}


def claude() -> Anthropic:
    if "claude" not in _clients:
        _clients["claude"] = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3)
    return _clients["claude"]


def tavily() -> TavilyClient:
    if "tavily" not in _clients:
        _clients["tavily"] = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return _clients["tavily"]
