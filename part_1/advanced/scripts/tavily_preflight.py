#!/usr/bin/env python3
"""One-credit, secret-safe Tavily connectivity preflight."""

from __future__ import annotations

import argparse
import json
import sys
from getpass import getpass
from pathlib import Path

from tavily import TavilyClient

COURSE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COURSE_ROOT))

from part_1.advanced.shared.config import settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Ignore the configured key and request a replacement with getpass.",
    )
    args = parser.parse_args()
    api_key = ""
    if args.prompt or not settings.tavily_api_key:
        api_key = getpass("Replacement Tavily API key (hidden): ").strip()
    else:
        api_key = settings.tavily_api_key
    if not api_key:
        print(json.dumps({"ok": False, "error_type": "MissingCredential"}))
        return 1
    try:
        response = TavilyClient(api_key=api_key).search(
            "official LangGraph durable execution documentation",
            search_depth="basic",
            max_results=1,
            include_answer=False,
            include_raw_content=False,
        )
        rows = response.get("results", []) if isinstance(response, dict) else []
        result = {
            "ok": bool(rows),
            "provider": "tavily",
            "result_count": len(rows),
            "url_schemes": sorted(
                {
                    str(item.get("url", "")).split(":", 1)[0]
                    for item in rows
                    if item.get("url")
                }
            ),
            "credential_in_output": False,
        }
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "provider": "tavily",
                    "error_type": type(exc).__name__,
                    "credential_in_output": False,
                },
                indent=2,
            )
        )
        return 1
    finally:
        api_key = ""


if __name__ == "__main__":
    raise SystemExit(main())
