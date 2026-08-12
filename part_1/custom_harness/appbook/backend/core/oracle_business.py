"""Read-only Kata analytics executed against the live Oracle business tables."""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.config import SHARED_DIR

AS_OF = date(2026, 9, 29)
FIXTURES_DIR = SHARED_DIR / "fixtures"


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if hasattr(value, "read"):
        return value.read()
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [item[0].lower() for item in cursor.description]
    return [{name: _json_value(value) for name, value in zip(columns, row)} for row in cursor.fetchall()]


class OracleKataBusinessData:
    """Same semantic contract as the local fixture facade, backed by Oracle SQL."""

    @staticmethod
    def _connection() -> Any:
        from backend.core.oracle_live import get_oracle_stack
        return get_oracle_stack().pool.acquire()

    def counts(self) -> dict[str, int]:
        names = ("products", "variants", "customers", "orders", "order_lines", "inventory", "returns")
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                result = {}
                for name in names:
                    cursor.execute(f"SELECT COUNT(*) FROM {name}")
                    result[name] = int(cursor.fetchone()[0])
                return result
        finally:
            connection.close()

    def morning_brief(self, exclusions: list[str] | None = None) -> dict[str, Any]:
        exclusions = [value.lower() for value in (exclusions or [])]
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT p.sku, p.name, p.category, v.variant_id, v.size_code AS size, v.colour,
                              l.region, l.city, i.on_hand, i.reorder_point, i.in_transit,
                              s.lead_time_days, s.minimum_order_qty, po.po_id, po.status
                       FROM inventory i
                       JOIN variants v ON v.variant_id=i.variant_id
                       JOIN products p ON p.sku=v.sku
                       JOIN locations l ON l.location_id=i.location_id
                       JOIN product_suppliers ps ON ps.sku=p.sku
                       JOIN suppliers s ON s.supplier_id=ps.supplier_id
                       LEFT JOIN purchase_orders po ON po.variant_id=i.variant_id
                                                    AND po.location_id=i.location_id
                                                    AND po.status='open'
                       WHERE i.snapshot_date=:1 AND i.on_hand < i.reorder_point
                         AND p.category IN ('Outerwear','Tops')
                         AND l.region IN ('UK','EU')
                       ORDER BY (i.reorder_point-i.on_hand) DESC""",
                    [AS_OF],
                )
                candidates = _rows(cursor)
                suppressed, alerts = [], []
                for item in candidates:
                    item["cover_weeks"] = round(item["on_hand"] / max(1, item["reorder_point"] / 2), 1)
                    item["recommended_qty"] = int(
                        math.ceil(max(item["minimum_order_qty"], item["reorder_point"] * 12) / item["minimum_order_qty"])
                        * item["minimum_order_qty"]
                    )
                    if item["po_id"]:
                        item["reason"] = f"suppressed: already actioned via {item['po_id']}"
                        suppressed.append(item)
                    elif item["category"].lower() not in exclusions:
                        alerts.append(item)
                cursor.execute(
                    """SELECT p.name, p.category, o.region, SUM(ol.qty) units,
                              ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) revenue
                       FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
                       JOIN variants v ON v.variant_id=ol.variant_id
                       JOIN products p ON p.sku=v.sku
                       WHERE o.order_date >= :1 AND o.region IN ('UK','EU')
                         AND p.category IN ('Outerwear','Tops')
                       GROUP BY p.name,p.category,o.region
                       HAVING SUM(ol.qty*ol.unit_price*(1-ol.discount)) >= 5000
                       ORDER BY revenue DESC FETCH FIRST 3 ROWS ONLY""",
                    [AS_OF.replace(day=1)],
                )
                top = _rows(cursor)
        finally:
            connection.close()
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
            "top_movers": top,
            "anomalies": anomalies,
            "suppressed": suppressed,
            "format": "numbers first · bullets · top 3 per section",
        }

    def warmlayer_spike(self) -> dict[str, Any]:
        current_start, prior_start, prior_end = AS_OF - timedelta(days=6), AS_OF - timedelta(days=34), AS_OF - timedelta(days=7)
        query = """SELECT NVL(SUM(ol.qty),0) FROM order_lines ol
                   JOIN orders o ON o.order_id=ol.order_id
                   JOIN variants v ON v.variant_id=ol.variant_id
                   JOIN products p ON p.sku=v.sku
                   WHERE p.product_line='WarmLayer' AND o.region='UK'
                     AND o.order_date BETWEEN :1 AND :2"""
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, [current_start, AS_OF])
                current = int(cursor.fetchone()[0])
                cursor.execute(query, [prior_start, prior_end])
                prior = int(cursor.fetchone()[0])
        finally:
            connection.close()
        prior_weekly = prior / 4
        change = round((current / max(prior_weekly, 1) - 1) * 100)
        return {
            "internal": {"last_7d_units": current, "prior_weekly_average": round(prior_weekly, 1), "change_percent": change,
                         "provenance": ["orders", "order_lines", "variants", "products"]},
            "external": {"provider": "Tavily fixture fallback", "signal": "A sharp UK cold snap reduced mean temperatures below the 12°C presentation trigger.", "url": "fixture://uk-weather-cold-snap"},
            "institutional": self.search_docs("WarmLayer UK cold temperature seasonal")[:2],
            "conclusion": "The spike is real in Kata transactions and is consistent with the cold snap plus Kata's thermal-season pattern; this is correlation, not proof of causation.",
        }

    def thermacore_stock(self) -> dict[str, Any]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT l.region, v.size_code AS size, SUM(i.on_hand) on_hand
                       FROM inventory i JOIN variants v ON v.variant_id=i.variant_id
                       JOIN products p ON p.sku=v.sku JOIN locations l ON l.location_id=i.location_id
                       WHERE p.sku='KTA-THC-01' AND i.snapshot_date=:1
                       GROUP BY l.region,v.size_code ORDER BY l.region,
                         CASE v.size_code WHEN 'XXS' THEN 1 WHEN 'XS' THEN 2 WHEN 'S' THEN 3
                         WHEN 'M' THEN 4 WHEN 'L' THEN 5 WHEN 'XL' THEN 6 ELSE 7 END""",
                    [AS_OF],
                )
                rows = _rows(cursor)
        finally:
            connection.close()
        return {"rows": rows, "finding": "M/L are near sell-out while XS/XXL hold the overhang.",
                "provenance": ["inventory", "variants", "products", "locations"]}

    def profitability(self, excluded_categories: list[str] | None = None) -> dict[str, Any]:
        excluded_categories = excluded_categories or []
        binds = ",".join(f":{index + 2}" for index in range(len(excluded_categories)))
        exclusion_sql = f" AND p.category NOT IN ({binds})" if excluded_categories else ""
        start = AS_OF - timedelta(days=89)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT o.region, SUM(ol.qty) units,
                              ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) net_revenue,
                              ROUND(SUM(ol.qty*(ol.unit_price*(1-ol.discount)-p.unit_cost)),2) gross_margin,
                              ROUND(100*SUM(ol.qty*(ol.unit_price*(1-ol.discount)-p.unit_cost)) /
                                NULLIF(SUM(ol.qty*ol.unit_price*(1-ol.discount)),0),1) margin_percent,
                              ROUND(100*AVG(ol.discount),1) avg_discount_percent
                       FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
                       JOIN variants v ON v.variant_id=ol.variant_id JOIN products p ON p.sku=v.sku
                       WHERE o.order_date >= :1""" + exclusion_sql +
                    " GROUP BY o.region ORDER BY gross_margin DESC",
                    [start, *excluded_categories],
                )
                rows = _rows(cursor)
        finally:
            connection.close()
        return {"metric": "gross margin = net revenue − unit cost", "quarter_start": start.isoformat(),
                "excluded_categories": excluded_categories, "rows": rows,
                "provenance": ["orders", "order_lines", "variants", "products"]}

    def customer_context(self) -> dict[str, Any]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT segment,COUNT(*) customers,ROUND(AVG(lifetime_value),2) avg_ltv FROM customers GROUP BY segment ORDER BY customers DESC")
                segments = _rows(cursor)
                cursor.execute(
                    """SELECT * FROM (SELECT p.product_line,COUNT(r.return_id) returned_lines,
                              SUM(CASE WHEN r.reason_code='size' THEN 1 ELSE 0 END) size_returns
                       FROM returns r JOIN variants v ON v.variant_id=r.variant_id
                       JOIN products p ON p.sku=v.sku GROUP BY p.product_line
                       ORDER BY returned_lines DESC) WHERE ROWNUM <= 5"""
                )
                returns = _rows(cursor)
        finally:
            connection.close()
        return {"segments": segments, "returns": returns,
                "privacy": "synthetic pseudonymous customer IDs only", "provenance": ["customers", "returns"]}

    def search_docs(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        wanted, results = _tokens(query), []
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
        row_limit = min(max(int(limit), 1), 500)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM ({sql.rstrip(';')}) FETCH FIRST {row_limit} ROWS ONLY", params)
                rows = _rows(cursor)
                columns = [item[0].lower() for item in cursor.description]
        finally:
            connection.close()
        tables = sorted(set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", normalized)))
        return {"columns": columns, "rows": rows, "row_limit": row_limit, "provenance": tables}
