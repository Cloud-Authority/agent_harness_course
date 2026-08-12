"""Decision boundary: OpenAI in live mode, deterministic teacher model locally."""
from __future__ import annotations

import re
import time


class DecisionModel:
    def decide(self, message: str) -> dict:
        time.sleep(0.006)  # makes the cache delta visible without slowing the workshop
        text = message.lower()
        if "morning brief" in text or text.strip() == "brief":
            return {"intent": "morning_brief", "tools": ["query_inventory"], "reason": "attention list requires thresholds and handled-item suppression"}
        if "warmlayer" in text and "spike" in text:
            return {"intent": "explain_spike", "tools": ["query_sales", "web_search", "search_company_docs"], "reason": "combine internal, external and institutional evidence"}
        if "thermacore" in text and ("stock" in text or "region" in text):
            return {"intent": "stock_visual", "tools": ["query_inventory"], "reason": "inventory by region and size"}
        if "profitable" in text or "profitability" in text or "margin" in text:
            return {"intent": "profitability", "tools": ["query_sales"], "reason": "canonical gross-margin metric"}
        if "calendar" in text or "schedule" in text or "book" in text:
            return {"intent": "calendar", "tools": ["get_calendar"], "reason": "calendar request"}
        return {"intent": "business_question", "tools": ["query_sales"], "reason": "ground answer in enterprise data"}


model = DecisionModel()
