"""Thin direct-API functions registered on the MemoRizz MemAgent (no MCP)."""
from __future__ import annotations

import sys
import json
from pathlib import Path
from urllib import request
from datetime import datetime, timedelta
from typing import Any, Callable

from backend.config import SHARED_DIR, settings

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from runtime import KataBusinessData  # noqa: E402

business = KataBusinessData()


class DirectToolbox:
    def __init__(self):
        self._tools: dict[str, tuple[str, Callable[..., Any]]] = {
            "query_sales": ("Sales, margin, customers and demand questions", self.query_sales),
            "query_inventory": ("Stock, restock and size-curve questions", self.query_inventory),
            "search_company_docs": ("Read-only Notion knowledge search", self.search_company_docs),
            "web_search": ("Tavily external-signal search", self.web_search),
            "get_calendar": ("Read the dedicated demo calendar", self.get_calendar),
            "create_event": ("Create an event after explicit user intent", self.create_event),
        }

    def catalog(self) -> list[dict[str, str]]:
        return [{"name": name, "description": value[0], "transport": "direct Python/API"} for name, value in self._tools.items()]

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name][1](**kwargs)

    def query_sales(self, question: str = "profitability", excluded_categories: list[str] | None = None) -> dict:
        if "customer" in question.lower() or "return" in question.lower():
            return business.customer_context()
        if "warm" in question.lower() or "spike" in question.lower():
            return business.warmlayer_spike()
        return business.profitability(excluded_categories)

    def query_inventory(self, question: str = "morning brief", excluded_categories: list[str] | None = None) -> dict:
        if "thermacore" in question.lower() and "across" in question.lower():
            return business.thermacore_stock()
        return business.morning_brief(excluded_categories)

    def search_company_docs(self, query: str) -> list[dict]:
        if settings.live and settings.notion_api_key:
            body = json.dumps({"query": query, "page_size": 10}).encode()
            req = request.Request("https://api.notion.com/v1/search", data=body, method="POST", headers={
                "Authorization": f"Bearer {settings.notion_api_key}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
            with request.urlopen(req, timeout=15) as response:
                payload = json.load(response)
            return [{"title": next((part.get("plain_text", "Untitled") for value in item.get("properties", {}).values()
                                    for part in value.get("title", [])), "Untitled"),
                     "page": item.get("id"), "url": item.get("url"), "score": 1.0}
                    for item in payload.get("results", [])]
        return business.search_docs(query)

    def web_search(self, query: str) -> dict:
        if settings.live and settings.tavily_api_key:
            body = json.dumps({"api_key": settings.tavily_api_key, "query": query, "max_results": 5}).encode()
            req = request.Request("https://api.tavily.com/search", data=body, method="POST", headers={"Content-Type": "application/json"})
            with request.urlopen(req, timeout=20) as response:
                return json.load(response)
        return business.warmlayer_spike()["external"]

    def get_calendar(self, date: str | None = None) -> dict:
        if settings.live and settings.google_calendar_credentials:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            credentials = Credentials.from_authorized_user_file(settings.google_calendar_credentials)
            events = build("calendar", "v3", credentials=credentials, cache_discovery=False).events().list(
                calendarId="primary", maxResults=10, singleEvents=True, orderBy="startTime").execute().get("items", [])
            return {"date": date or "upcoming", "timezone": "Europe/London", "events": events, "mode": "live"}
        return {"date": date or "next Thursday", "timezone": "Europe/London",
                "events": [{"start": "14:00", "title": "Weekly merchandise review"}], "mode": settings.mode}

    def create_event(self, title: str, start: str = "10:30") -> dict:
        hour = int(start.split(":")[0])
        if hour < 10:
            raise ValueError("Saved preference: no meetings before 10:00 Europe/London")
        if settings.live and settings.google_calendar_credentials:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            credentials = Credentials.from_authorized_user_file(settings.google_calendar_credentials)
            payload = {"summary": title, "start": {"dateTime": f"2026-10-01T{start}:00+01:00", "timeZone": "Europe/London"},
                       "end": {"dateTime": "2026-10-01T11:00:00+01:00", "timeZone": "Europe/London"}}
            return build("calendar", "v3", credentials=credentials, cache_discovery=False).events().insert(calendarId="primary", body=payload).execute()
        return {"created": True, "title": title, "start": start, "timezone": "Europe/London", "demo": True}


toolbox = DirectToolbox()
