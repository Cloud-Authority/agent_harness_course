"""Small, synthetic fixtures used by the advanced harnesses.

The workflow fixture is intentionally stable so idempotency and replay can be
asserted byte-for-byte. The research fixture is an explicitly labelled network
fallback; the default research path is Tavily.
"""

from __future__ import annotations

from copy import deepcopy


COMPLIANCE_CASE = {
    "reporting_period": "2026-Q3",
    "supplier": {
        "supplier_id": "SUP-1042",
        "name": "Northstar Textiles (synthetic)",
        "region": "EU",
        "country": "Portugal",
        "risk_tier": "high",
        "annual_spend_usd": 4_800_000,
        "criticality": "production-critical",
    },
    "sanctions_screening": {
        "screening_id": "SCR-2026-08-17-1042",
        "checked_at": "2026-08-17T09:30:00Z",
        "possible_match": False,
        "source": "authoritative synthetic screening feed",
    },
    "controls": [
        {
            "control_id": "CTRL-01",
            "name": "Modern-slavery attestation",
            "status": "passed",
            "evidence_id": "EV-203",
            "evidence_age_days": 43,
        },
        {
            "control_id": "CTRL-02",
            "name": "Restricted-substance certificate",
            "status": "expired",
            "evidence_id": "EV-219",
            "evidence_age_days": 401,
        },
        {
            "control_id": "CTRL-03",
            "name": "Factory audit remediation",
            "status": "open",
            "evidence_id": "EV-227",
            "evidence_age_days": 17,
            "remediation_owner_role": "supplier-quality-manager",
        },
        {
            "control_id": "CTRL-04",
            "name": "Sanctions screening",
            "status": "passed",
            "evidence_id": "EV-231",
            "evidence_age_days": 2,
        },
    ],
}


PROCEDURAL_MEMORY = {
    "memory_type": "procedural",
    "title": "Procedural-memory routing rule",
    "text": (
        "Canonical operating procedures are SHA-versioned SKILL.md documents in "
        "the semantic skillbox. Retrieve a small skill manifest first, then load "
        "only the full approved skills selected for the current objective."
    ),
    "version": "skillbox-routing-v1",
}


SEMANTIC_MEMORY = {
    "memory_type": "semantic",
    "title": "Compliance business rules",
    "text": (
        "Certificates older than 365 days are expired. Any expired certificate "
        "blocks publication until a human accepts the remediation plan. Open audit "
        "remediation raises risk but does not alone prohibit a draft. A possible "
        "sanctions match blocks the case. High-risk suppliers always require a named "
        "human publication decision."
    ),
    "rule_ids": [
        "RULE-FRESH-365",
        "RULE-SANCTIONS-BLOCK",
        "RULE-HIGH-RISK-OWNER",
        "RULE-HITL-PUBLISH",
    ],
}


RESEARCH_FIXTURES = {
    "market": [
        {
            "title": "Durable agent systems move beyond single-turn prototypes",
            "url": "https://example.test/research/durable-agent-systems",
            "content": (
                "Production teams increasingly require checkpoint recovery, bounded "
                "tools, and auditable human approval for long-running agent work."
            ),
            "score": 0.94,
        },
        {
            "title": "Memory-first research systems consolidate evidence",
            "url": "https://example.test/research/memory-first-systems",
            "content": (
                "Shared evidence pools with provenance and contradiction review can "
                "reduce repeated searches across research sessions."
            ),
            "score": 0.91,
        },
    ],
    "competition": [
        {
            "title": "Agent frameworks compete on orchestration and observability",
            "url": "https://example.test/research/framework-competition",
            "content": (
                "Framework differentiation includes graph execution, checkpoints, "
                "multi-agent coordination, tracing, and deployment controls."
            ),
            "score": 0.89,
        }
    ],
    "risk": [
        {
            "title": "Parallel agents can amplify shared evidence errors",
            "url": "https://example.test/research/parallel-agent-risk",
            "content": (
                "Parallel workers increase breadth but can repeat unsupported claims "
                "unless evidence is deduplicated and contradictions are surfaced."
            ),
            "score": 0.93,
        }
    ],
}


def compliance_case() -> dict:
    return deepcopy(COMPLIANCE_CASE)


def fixture_search(worker: str) -> list[dict]:
    return deepcopy(RESEARCH_FIXTURES.get(worker, RESEARCH_FIXTURES["market"]))
