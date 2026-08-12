"""Read-only enterprise-data facade backed by the deterministic Kata seed."""
from __future__ import annotations

import math
import re
import sqlite3
import sys
from datetime import timedelta
from collections import defaultdict
from pathlib import Path
from typing import Any

SHARED = Path(__file__).resolve().parents[1]
SEED_DIR = SHARED / "seed"
FIXTURES_DIR = SHARED / "fixtures"
if str(SEED_DIR) not in sys.path:
    sys.path.insert(0, str(SEED_DIR))

from generate_seed_data import AS_OF, DB_PATH, build_sqlite  # noqa: E402


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}


class KataBusinessData:
    """Canonical query functions. Both builds wrap these with different tool plumbing."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        build_sqlite(db_path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            names = ("products", "variants", "customers", "orders", "order_lines", "inventory", "returns")
            return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}

    def morning_brief(self, exclusions: list[str] | None = None) -> dict[str, Any]:
        exclusions = [value.lower() for value in (exclusions or [])]
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT p.sku, p.name, p.category, v.variant_id, v.size, v.colour,
                          l.region, l.city, i.on_hand, i.reorder_point, i.in_transit,
                          s.lead_time_days, s.minimum_order_qty,
                          po.po_id, po.status
                   FROM inventory i
                   JOIN variants v ON v.variant_id=i.variant_id
                   JOIN products p ON p.sku=v.sku
                   JOIN locations l ON l.location_id=i.location_id
                   JOIN product_suppliers ps ON ps.sku=p.sku
                   JOIN suppliers s ON s.supplier_id=ps.supplier_id
                   LEFT JOIN purchase_orders po ON po.variant_id=i.variant_id
                                                AND po.location_id=i.location_id
                                                AND po.status='open'
                   WHERE i.snapshot_date=? AND i.on_hand < i.reorder_point
                     AND p.category IN ('Outerwear','Tops')
                     AND l.region IN ('UK','EU')
                   ORDER BY (i.reorder_point-i.on_hand) DESC""",
                (AS_OF.isoformat(),),
            ).fetchall()
            suppressed, alerts = [], []
            for row in rows:
                item = dict(row)
                item["cover_weeks"] = round(row["on_hand"] / max(1, row["reorder_point"] / 2), 1)
                item["recommended_qty"] = int(math.ceil(max(row["minimum_order_qty"], row["reorder_point"] * 12) / row["minimum_order_qty"]) * row["minimum_order_qty"])
                if row["po_id"]:
                    item["reason"] = f"suppressed: already actioned via {row['po_id']}"
                    suppressed.append(item)
                elif row["category"].lower() not in exclusions:
                    alerts.append(item)

            top = conn.execute(
                """SELECT p.name, p.category, o.region, SUM(ol.qty) units,
                          ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) revenue
                   FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
                   JOIN variants v ON v.variant_id=ol.variant_id JOIN products p ON p.sku=v.sku
                   WHERE o.order_date >= ? AND o.region IN ('UK','EU')
                     AND p.category IN ('Outerwear','Tops')
                   GROUP BY p.name,p.category,o.region HAVING revenue >= 5000
                   ORDER BY revenue DESC LIMIT 3""",
                ((AS_OF.replace(day=1)).isoformat(),),
            ).fetchall()
        warm = self.warmlayer_spike()["internal"]
        anomalies = [
            {"signal": "UK WarmLayer", "change": f"{warm['change_percent']:+d}% vs prior four-week weekly average", "why": "no internal promotion detected"},
            {"signal": "EU margin", "change": "volume healthy; gross-margin rate compressed", "why": "average discount is elevated"},
            {"signal": "TrueDenim returns", "change": "27% planted return tendency", "why": "size reason dominates"},
        ]
        return {
            "as_of": AS_OF.isoformat(),
            "scope": {"categories": ["Outerwear", "Tops"], "regions": ["UK", "EU"], "revenue_floor_gbp": 5000},
            "restock": alerts[:3],
            "top_movers": [dict(row) for row in top],
            "anomalies": anomalies[:3],
            "suppressed": suppressed,
            "format": "numbers first · bullets · top 3 per section",
        }

    def warmlayer_spike(self) -> dict[str, Any]:
        current_start = (AS_OF - timedelta(days=6)).isoformat()
        prior_start = (AS_OF - timedelta(days=34)).isoformat()
        prior_end = (AS_OF - timedelta(days=7)).isoformat()
        with self.connect() as conn:
            query = """SELECT COALESCE(SUM(ol.qty),0) FROM order_lines ol
                       JOIN orders o ON o.order_id=ol.order_id
                       JOIN variants v ON v.variant_id=ol.variant_id
                       JOIN products p ON p.sku=v.sku
                       WHERE p.product_line='WarmLayer' AND o.region='UK'
                         AND o.order_date BETWEEN ? AND ?"""
            current = conn.execute(query, (current_start, AS_OF.isoformat())).fetchone()[0]
            prior = conn.execute(query, (prior_start, prior_end)).fetchone()[0]
        prior_weekly = prior / 4
        change = round((current / max(prior_weekly, 1) - 1) * 100)
        seasonal = self.search_docs("WarmLayer UK cold temperature seasonal")[:2]
        return {
            "internal": {"last_7d_units": current, "prior_weekly_average": round(prior_weekly, 1), "change_percent": change,
                         "provenance": ["orders", "order_lines", "variants", "products"]},
            "external": {"provider": "Tavily fixture fallback", "signal": "A sharp UK cold snap reduced mean temperatures below the 12°C presentation trigger.",
                         "url": "fixture://uk-weather-cold-snap"},
            "institutional": seasonal,
            "conclusion": "The spike is real in Kata transactions and is consistent with the cold snap plus Kata's documented thermal-season pattern; this is correlation, not proof of causation.",
        }

    def thermacore_stock(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT l.region, v.size, SUM(i.on_hand) on_hand
                   FROM inventory i JOIN variants v ON v.variant_id=i.variant_id
                   JOIN products p ON p.sku=v.sku JOIN locations l ON l.location_id=i.location_id
                   WHERE p.sku='KTA-THC-01' AND i.snapshot_date=?
                   GROUP BY l.region,v.size ORDER BY l.region,
                     CASE v.size WHEN 'XXS' THEN 1 WHEN 'XS' THEN 2 WHEN 'S' THEN 3
                     WHEN 'M' THEN 4 WHEN 'L' THEN 5 WHEN 'XL' THEN 6 ELSE 7 END""",
                (AS_OF.isoformat(),),
            ).fetchall()
        return {"rows": [dict(row) for row in rows], "finding": "M/L are near sell-out while XS/XXL hold the overhang.",
                "provenance": ["inventory", "variants", "products", "locations"]}

    def profitability(self, excluded_categories: list[str] | None = None) -> dict[str, Any]:
        excluded_categories = excluded_categories or []
        placeholders = ",".join("?" for _ in excluded_categories)
        exclusion_sql = f" AND p.category NOT IN ({placeholders})" if excluded_categories else ""
        start = (AS_OF - __import__("datetime").timedelta(days=89)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT o.region, SUM(ol.qty) units,
                          ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) net_revenue,
                          ROUND(SUM(ol.qty*(ol.unit_price*(1-ol.discount)-p.unit_cost)),2) gross_margin,
                          ROUND(100*SUM(ol.qty*(ol.unit_price*(1-ol.discount)-p.unit_cost)) /
                            NULLIF(SUM(ol.qty*ol.unit_price*(1-ol.discount)),0),1) margin_percent,
                          ROUND(100*AVG(ol.discount),1) avg_discount_percent
                   FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
                   JOIN variants v ON v.variant_id=ol.variant_id JOIN products p ON p.sku=v.sku
                   WHERE o.order_date >= ?""" + exclusion_sql +
                " GROUP BY o.region ORDER BY gross_margin DESC",
                (start, *excluded_categories),
            ).fetchall()
        return {"metric": "gross margin = net revenue − unit cost", "quarter_start": start,
                "excluded_categories": excluded_categories, "rows": [dict(row) for row in rows],
                "provenance": ["orders", "order_lines", "variants", "products"]}

    def customer_context(self) -> dict[str, Any]:
        with self.connect() as conn:
            segments = conn.execute("SELECT segment, COUNT(*) customers, ROUND(AVG(lifetime_value),2) avg_ltv FROM customers GROUP BY segment ORDER BY customers DESC").fetchall()
            returns = conn.execute("""SELECT p.product_line, COUNT(r.return_id) returned_lines,
                                      SUM(CASE WHEN r.reason_code='size' THEN 1 ELSE 0 END) size_returns
                               FROM returns r JOIN variants v ON v.variant_id=r.variant_id
                               JOIN products p ON p.sku=v.sku GROUP BY p.product_line
                               ORDER BY returned_lines DESC LIMIT 5""").fetchall()
        return {"segments": [dict(r) for r in segments], "returns": [dict(r) for r in returns],
                "privacy": "synthetic pseudonymous customer IDs only", "provenance": ["customers", "returns"]}

    def search_docs(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        wanted = _tokens(query)
        results = []
        for path in sorted((FIXTURES_DIR / "notion_pages").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            overlap = wanted & _tokens(text)
            if overlap:
                body = " ".join(line.strip() for line in text.splitlines() if line and not line.startswith("#"))
                results.append({"title": text.splitlines()[0].lstrip("# "), "page": path.name,
                                "score": round(len(overlap) / max(1, len(wanted)), 3), "excerpt": body[:360]})
        return sorted(results, key=lambda item: (-item["score"], item["page"]))[:limit]

    def query_read_only(self, sql: str, params: tuple = (), limit: int = 100) -> dict[str, Any]:
        normalized = sql.strip().lower()
        if not normalized.startswith("select") or ";" in normalized.rstrip(";"):
            raise ValueError("Only one read-only SELECT statement is allowed")
        if re.search(r"\b(cross\s+join|insert|update|delete|merge|drop|alter|create|grant)\b", normalized):
            raise ValueError("Query rejected by the read-only semantic-layer guardrail")
        with self.connect() as conn:
            cursor = conn.execute(f"SELECT * FROM ({sql.rstrip(';')}) LIMIT ?", (*params, min(limit, 500)))
            tables = sorted(set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", normalized)))
            return {"columns": [c[0] for c in cursor.description], "rows": [dict(row) for row in cursor],
                    "row_limit": min(limit, 500), "provenance": tables}
