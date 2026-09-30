"""Settings and clients for the survey-paper harness."""
from __future__ import annotations

import os
from dataclasses import dataclass

from anthropic import Anthropic
from tavily import TavilyClient


@dataclass(frozen=True)
class SurveyConfig:
    model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    effort: str = os.getenv("SURVEY_EFFORT", "medium")
    sections: int = 6                    # thematic sections between the introduction and the outlook
    queries_per_section: int = 2         # web searches for each section in the first round
    results_per_query: int = 8
    sources_per_section: int = 6         # pages read in full for each section
    min_citations_per_section: int = 3
    min_words_per_section: int = 350
    max_rounds: int = 2                  # a review may send the harness back to gather once
    read_batch: int = 4                  # sources read in one model call
    scholarly_domains: tuple = ("arxiv.org", "openreview.net", "aclanthology.org", "dl.acm.org",
                                "ieeexplore.ieee.org", "proceedings.neurips.cc", "proceedings.mlr.press",
                                "semanticscholar.org", "nature.com", "sciencedirect.com", "springer.com")
    crash_after: str = os.getenv("SURVEY_CRASH_AFTER", "")


CFG = SurveyConfig()
_clients: dict[str, object] = {}


def claude() -> Anthropic:
    if "claude" not in _clients:
        _clients["claude"] = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3)
    return _clients["claude"]


def tavily() -> TavilyClient:
    if "tavily" not in _clients:
        _clients["tavily"] = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return _clients["tavily"]
