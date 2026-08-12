"""Progressive disclosure: metadata always visible, full instructions on match."""
from __future__ import annotations

import re

from backend.config import settings

SKILLS = {
    "compose_morning_brief": {"description": "Personalised daily attention digest", "triggers": ["morning", "brief", "attention"],
        "instructions": "Recall scope, thresholds, exclusions and handled work. Sections: restock, top movers, anomalies. Numbers first; top three; suppress actioned items."},
    "restock_recommendation": {"description": "Core/seasonal stock decision", "triggers": ["stock", "restock", "cover", "inventory"],
        "instructions": "Return SKU, variant, location, cover, lead time, MOQ-rounded quantity and rationale. Check open PO before alerting."},
    "weekly_review_prep": {"description": "Prepare weekly merchandising review", "triggers": ["weekly", "review", "prep"],
        "instructions": "Retrieve prior review notes, calculate current deltas, and separate new decisions from open actions."},
    "profitability_analysis": {"description": "Canonical regional profit comparison", "triggers": ["profit", "margin", "profitable"],
        "instructions": "Rank by gross-margin value, show margin percent, unit volume, discount and source tables."},
    "demand_anomaly_investigation": {"description": "Triangulate unusual demand with governed evidence", "triggers": ["spike", "anomaly", "demand", "trend", "trending"],
        "instructions": "Compare the recent window to its baseline, check internal promotions, retrieve approved seasonal guidance and a dated external signal, then distinguish correlation from causation."},
    "size_curve_diagnosis": {"description": "Find broken size curves by product and region", "triggers": ["size", "curve", "broken", "thermacore"],
        "instructions": "Aggregate stock by region and size, compare the shape rather than only total units, identify constrained and overstocked sizes, and cite inventory snapshot dates."},
    "returns_root_cause": {"description": "Analyse return concentration and reasons", "triggers": ["return", "returns", "quality", "fit"],
        "instructions": "Rank product lines by returned units, split reason codes, protect customer privacy and recommend investigation rather than asserting causality."},
    "supplier_risk_review": {"description": "Assess replenishment lead-time and reliability risk", "triggers": ["supplier", "lead", "reliability", "risk"],
        "instructions": "Join the selected SKU to its declared supplier, show lead time, reliability and MOQ, then relate those constraints to the stock decision."},
    "purchase_order_suppression": {"description": "Prevent duplicate action when an open PO exists", "triggers": ["purchase", "order", "already", "handled", "suppress"],
        "instructions": "Look for an open purchase order matching variant and location before raising an alert; return the PO ID when the issue is already covered."},
    "catalog_assortment_review": {"description": "Compare product, collection and seasonal assortment", "triggers": ["catalog", "assortment", "collection", "range"],
        "instructions": "Group products by category, collection and core/seasonal status; show style, variant and available-stock counts with the current snapshot date."},
    "promotion_memory_review": {"description": "Review ScratchFS notes before durable-memory promotion", "triggers": ["promote", "memory", "scratch", "note"],
        "instructions": "Inspect only session files opted into promotion, show the staged chunks, end the logical session, then verify which facts reached OAMP."},
}


def disclose(query: str) -> dict:
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT skill_name,description,body_sha256,
                      VECTOR_DISTANCE(embedding,VECTOR_EMBEDDING({settings.oamp_indb_embed_model}
                        USING :query AS DATA),COSINE) distance
                      FROM erpa_skill_registry WHERE status='ACTIVE' ORDER BY distance
                      FETCH APPROX FIRST 3 ROWS ONLY""",
                    {"query": query},
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        matched = [{
            "name": name, "description": description,
            "body_sha256": body_sha256, "distance": float(distance),
            "disclosure": "manifest only; call load_skill for the body",
        } for name, description, body_sha256, distance in rows]
        metadata = [{"name": name, "description": value["description"]} for name, value in SKILLS.items()]
        return {"metadata": metadata, "matched": matched, "token_comparison": {
            "dump_everything": sum(len(item["instructions"].split()) for item in SKILLS.values()),
            "progressive": sum(len(item["description"].split()) + 4 for item in matched),
            "saved": "full bodies remain outside context until load_skill",
        }}
    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    metadata = [{"name": name, "description": spec["description"]} for name, spec in SKILLS.items()]
    ranked = []
    for name, spec in SKILLS.items():
        trigger_overlap = words & set(spec["triggers"])
        if not trigger_overlap:
            continue
        description_words = set(re.findall(r"[a-z0-9]+", spec["description"].lower()))
        score = len(trigger_overlap) * 3 + len(words & description_words)
        ranked.append((score, name, spec))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    # Retrieval returns compact manifests only. The selected full body is loaded
    # separately by ``demonstrate_disclosure`` below.
    matched = [{"name": name, "description": spec["description"], "score": score,
                "disclosure": "manifest only; selected body not yet in context"}
               for score, name, spec in ranked[:3]]
    metadata_tokens = sum(len(item["description"].split()) + 2 for item in metadata)
    full_catalog_tokens = sum(len(spec["instructions"].split()) for spec in SKILLS.values()) + metadata_tokens
    selected_body_tokens = len(ranked[0][2]["instructions"].split()) if ranked else 0
    disclosed_tokens = metadata_tokens + selected_body_tokens
    return {"metadata": metadata, "matched": matched, "token_comparison": {
        "dump_everything": full_catalog_tokens, "progressive": disclosed_tokens,
        "saved": full_catalog_tokens - disclosed_tokens}}


def demonstrate_disclosure(query: str) -> dict:
    """Retrieve manifests, then load only the top approved skill body."""
    result = disclose(query)
    selected = result["matched"][0]["name"] if result["matched"] else None
    body = None
    source = None
    if selected and settings.live:
        from backend.core.oracle_live import get_oracle_stack

        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT body,body_sha256 FROM erpa_skill_registry WHERE skill_name=:1 AND status='ACTIVE'",
                    [selected],
                )
                row = cursor.fetchone()
                if row:
                    body = row[0].read() if hasattr(row[0], "read") else str(row[0])
                    source = {"registry": "ERPA_SKILL_REGISTRY", "sha256": row[1]}
        finally:
            connection.close()
    elif selected:
        body = SKILLS[selected]["instructions"]
        source = {"registry": "local approved skill mirror", "sha256": "deterministic teaching body"}
    return {"query": query, **result,
            "disclosed_skill": {"name": selected, "instructions": body, "source": source} if selected else None,
            "sequence": ["retrieve compact manifests", "select top approved match", "load one full body"]}
