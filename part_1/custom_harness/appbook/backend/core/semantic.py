"""Schema catalog, glossary mappings, canonical metrics and SQL guardrails."""
from __future__ import annotations

import re
import sys
from typing import Any

from backend.config import SHARED_DIR, settings

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
from runtime import KataBusinessData  # noqa: E402


SCHEMA_CATALOG = {
    "products": {"description": "product master and commercial attributes", "pk": "sku",
                 "columns": {"sku": "TEXT", "name": "TEXT", "product_line": "TEXT", "category": "TEXT", "collection_name": "TEXT", "season": "TEXT", "launch_date": "DATE", "base_price": "NUMBER", "unit_cost": "NUMBER", "fabric": "TEXT", "is_core": "BOOLEAN"},
                 "joins": {"variants": "products.sku = variants.sku"}},
    "variants": {"description": "sellable size and colour variants", "pk": "variant_id",
                 "columns": {"variant_id": "TEXT", "sku": "TEXT", "size": "TEXT", "colour": "TEXT"},
                 "joins": {"products": "variants.sku = products.sku", "inventory": "variants.variant_id = inventory.variant_id", "order_lines": "variants.variant_id = order_lines.variant_id"}},
    "inventory": {"description": "dated stock snapshot by variant and location", "pk": ["variant_id", "location_id", "snapshot_date"],
                  "columns": {"variant_id": "TEXT", "location_id": "TEXT", "on_hand": "INTEGER", "in_transit": "INTEGER", "reserved": "INTEGER", "reorder_point": "INTEGER", "snapshot_date": "DATE"},
                  "joins": {"variants": "inventory.variant_id = variants.variant_id", "locations": "inventory.location_id = locations.location_id"}},
    "locations": {"description": "regional distribution centres, stores and 3PLs", "pk": "location_id",
                  "columns": {"location_id": "TEXT", "region": "TEXT", "type": "TEXT", "country": "TEXT", "city": "TEXT"},
                  "joins": {"inventory": "locations.location_id = inventory.location_id"}},
    "orders": {"description": "order header, customer, date, region and channel", "pk": "order_id",
               "columns": {"order_id": "TEXT", "customer_id": "TEXT", "order_date": "DATE", "region": "TEXT", "channel": "TEXT"},
               "joins": {"customers": "orders.customer_id = customers.customer_id", "order_lines": "orders.order_id = order_lines.order_id"}},
    "order_lines": {"description": "units, ticket price and fractional discount", "pk": "line_id",
                     "columns": {"line_id": "INTEGER", "order_id": "TEXT", "variant_id": "TEXT", "qty": "INTEGER", "unit_price": "NUMBER", "discount": "NUMBER"},
                     "joins": {"orders": "order_lines.order_id = orders.order_id", "variants": "order_lines.variant_id = variants.variant_id"}},
    "returns": {"description": "returned units and reason code", "pk": "return_id",
                "columns": {"return_id": "INTEGER", "order_id": "TEXT", "variant_id": "TEXT", "qty": "INTEGER", "reason_code": "TEXT", "return_date": "DATE"},
                "joins": {"orders": "returns.order_id = orders.order_id", "variants": "returns.variant_id = variants.variant_id"}},
    "customers": {"description": "synthetic pseudonymous customer aggregates", "pk": "customer_id",
                  "columns": {"customer_id": "TEXT", "region": "TEXT", "segment": "TEXT", "first_order_date": "DATE", "lifetime_orders": "INTEGER", "lifetime_value": "NUMBER"},
                  "joins": {"orders": "customers.customer_id = orders.customer_id"}},
    "suppliers": {"description": "supplier lead time, reliability and minimum order quantity", "pk": "supplier_id",
                  "columns": {"supplier_id": "TEXT", "name": "TEXT", "lead_time_days": "INTEGER", "reliability_score": "NUMBER", "minimum_order_qty": "INTEGER"},
                  "joins": {"product_suppliers": "suppliers.supplier_id = product_suppliers.supplier_id"}},
    "product_suppliers": {"description": "declared product to supplier relationship", "pk": "sku",
                          "columns": {"sku": "TEXT", "supplier_id": "TEXT"},
                          "joins": {"products": "product_suppliers.sku = products.sku", "suppliers": "product_suppliers.supplier_id = suppliers.supplier_id"}},
    "purchase_orders": {"description": "open and completed replenishment actions", "pk": "po_id",
                        "columns": {"po_id": "TEXT", "variant_id": "TEXT", "location_id": "TEXT", "qty": "INTEGER", "raised_date": "DATE", "status": "TEXT"},
                        "joins": {"variants": "purchase_orders.variant_id = variants.variant_id", "locations": "purchase_orders.location_id = locations.location_id"}},
}

GLOSSARY = {
    "cover weeks": "(inventory.on_hand - inventory.reserved) / (trailing_28d_units / 4)",
    "cover": "alias → cover weeks",
    "sell-through": "net units sold / units received for the stated window",
    "st%": "alias → sell-through",
    "size curve": "units or on-hand share by variants.size within product + colour",
    "margin": "SUM(qty * (unit_price * (1-discount) - products.unit_cost))",
    "most profitable": "rank by gross margin value; include margin percent",
    "gmroi": "trailing-12-month gross margin / average inventory cost",
    "core vs seasonal": "products.is_core = 1 replenishes; 0 normally marks down near exit",
}

METRICS = {
    "net_revenue": "SUM(qty * unit_price * (1-discount)) less returned value",
    "gross_margin": GLOSSARY["margin"],
    "gross_margin_percent": "gross_margin / NULLIF(net_revenue, 0)",
    "cover_weeks": GLOSSARY["cover weeks"],
    "sell_through": GLOSSARY["sell-through"],
    "gmroi": GLOSSARY["gmroi"],
}


class SemanticLayer:
    def __init__(self):
        if settings.live:
            from backend.core.oracle_business import OracleKataBusinessData

            self.data = OracleKataBusinessData()
        else:
            self.data = KataBusinessData()

    def catalog(self) -> dict[str, Any]:
        result = {"tables": SCHEMA_CATALOG, "glossary": GLOSSARY, "metrics": METRICS,
                  "search": "Oracle in-database vector catalog" if settings.live else "deterministic token retrieval teaching mirror",
                  "sources": ["governed views", "table/column comments", "curated hints", "V$SQL workload shapes"],
                  "guardrails": ["read-only SELECT", "no CROSS JOIN", "500-row maximum", "declared relationship paths"],
                  "provenance": "every query result carries source tables"}
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT source_type,COUNT(*) FROM erpa_semantic_catalog GROUP BY source_type")
                    result["living_catalog"] = {name.lower(): int(count) for name, count in cursor.fetchall()}
                    cursor.execute(
                        "SELECT state,next_run_date FROM user_scheduler_jobs "
                        "WHERE job_name='ERPA_SEMANTIC_REFRESH_JOB'"
                    )
                    row = cursor.fetchone()
                    result["refresh_job"] = {
                        "name": "ERPA_SEMANTIC_REFRESH_JOB",
                        "state": row[0] if row else "NOT_INSTALLED",
                        "next_run": str(row[1]) if row else None,
                    }
            finally:
                connection.close()
        return result

    def search_catalog(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT catalog_id,source_type,catalog_text,
                          VECTOR_DISTANCE(embedding,VECTOR_EMBEDDING({settings.oamp_indb_embed_model}
                            USING :query AS DATA),COSINE) distance
                          FROM erpa_semantic_catalog ORDER BY distance
                          FETCH APPROX FIRST :limit ROWS ONLY""",
                        {"query": query, "limit": limit},
                    )
                    columns = [item[0].lower() for item in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                connection.close()
        wanted = set(re.findall(r"[a-z0-9]+", query.lower()))
        results = []
        for table, info in SCHEMA_CATALOG.items():
            document = " ".join((table, info["description"], *info["columns"].keys(), *info["joins"].keys()))
            overlap = wanted & set(re.findall(r"[a-z0-9]+", document.lower()))
            if overlap:
                results.append({"table": table, "score": round(len(overlap) / max(1, len(wanted)), 3),
                                "columns": info["columns"], "relationships": info["joins"]})
        return sorted(results, key=lambda row: (-row["score"], row["table"]))[:limit]

    def meaning(self, question: str) -> dict[str, Any]:
        text = question.lower()
        mappings = {key: value for key, value in GLOSSARY.items() if key in text}
        tables = [row.get("table", row.get("catalog_id", "semantic_fact")) for row in self.search_catalog(question)]
        if "profit" in text or "margin" in text:
            tables = ["orders", "order_lines", "variants", "products"]
            mappings["most profitable"] = GLOSSARY["most profitable"]
            mappings["margin"] = GLOSSARY["margin"]
        return {"question": question, "mappings": mappings, "tables": list(dict.fromkeys(tables)),
                "joins": ["orders.order_id = order_lines.order_id", "order_lines.variant_id = variants.variant_id", "variants.sku = products.sku"]}

    def ask(self, question: str, exclusions: list[str] | None = None) -> dict[str, Any]:
        text = question.lower()
        if ((any(term in text for term in ("how many", "how much", "count")) and "product" in text)
                or (any(term in text for term in ("highest", "most", "largest", "total"))
                    and any(term in text for term in ("stock", "inventory")))):
            result = self.inventory_summary()
        elif "profit" in text or "margin" in text:
            result = self.data.profitability(exclusions)
        elif "stock" in text and "thermacore" in text:
            result = self.data.thermacore_stock()
        elif "customer" in text or "return" in text:
            result = self.data.customer_context()
        elif "warm" in text and "spike" in text:
            result = self.data.warmlayer_spike()
        elif any(term in text for term in ("trend", "demand", "top seller", "best seller", "performance", "performing")):
            regions = [region for region in ("UK", "EU", "US", "JP", "SEA") if region.lower() in text]
            result = self.demand_performance(regions)
        else:
            result = self.data.morning_brief(exclusions)
        return {"semantic_context": self.meaning(question), "result": result}

    def inventory_summary(self) -> dict[str, Any]:
        """Return catalog counts and product-level available inventory."""
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM products")
                    product_count = int(cursor.fetchone()[0])
                    cursor.execute("SELECT COUNT(*) FROM variants")
                    variant_count = int(cursor.fetchone()[0])
                    cursor.execute(
                        """SELECT p.sku,p.name,SUM(GREATEST(i.on_hand-i.reserved,0)) available
                           FROM products p JOIN variants v ON v.sku=p.sku
                           JOIN inventory i ON i.variant_id=v.variant_id
                           GROUP BY p.sku,p.name ORDER BY available DESC FETCH FIRST 5 ROWS ONLY"""
                    )
                    rows = [{"sku": sku, "name": name, "available": int(available)}
                            for sku, name, available in cursor.fetchall()]
                    cursor.execute("SELECT SUM(GREATEST(on_hand-reserved,0)) FROM inventory")
                    available = int(cursor.fetchone()[0] or 0)
            finally:
                connection.close()
        else:
            from backend.core import store

            store.initialize()
            with store.connect() as connection:
                product_count = int(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0])
                variant_count = int(connection.execute("SELECT COUNT(*) FROM variants").fetchone()[0])
                rows = [dict(row) for row in connection.execute(
                    """SELECT p.sku,p.name,SUM(MAX(i.on_hand-i.reserved,0)) available
                       FROM products p JOIN variants v ON v.sku=p.sku
                       JOIN inventory i ON i.variant_id=v.variant_id
                       GROUP BY p.sku,p.name ORDER BY available DESC LIMIT 5"""
                ).fetchall()]
                available = int(connection.execute(
                    "SELECT SUM(MAX(on_hand-reserved,0)) FROM inventory"
                ).fetchone()[0] or 0)
        return {"product_count": product_count, "variant_count": variant_count,
                "available_units": available, "top_stocked_products": rows,
                "provenance": ["products", "variants", "inventory"]}

    def demand_performance(self, regions: list[str] | None = None) -> dict[str, Any]:
        """Rank current-month product demand, optionally inside named regions."""
        valid_regions = [item for item in (regions or []) if item in {"UK", "EU", "US", "JP", "SEA"}]
        if settings.live:
            from backend.core.oracle_live import get_oracle_stack

            region_sql = " AND o.region IN (" + ",".join(f":{index + 1}" for index in range(len(valid_regions))) + ")" if valid_regions else ""
            connection = get_oracle_stack().pool.acquire()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """SELECT p.name,o.region,SUM(ol.qty) units,
                                  ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) revenue
                           FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
                           JOIN variants v ON v.variant_id=ol.variant_id
                           JOIN products p ON p.sku=v.sku
                           WHERE o.order_date >= DATE '2026-09-01'""" + region_sql +
                        " GROUP BY p.name,o.region ORDER BY revenue DESC FETCH FIRST 5 ROWS ONLY",
                        valid_regions,
                    )
                    rows = [{name: _value for name, _value in zip(
                        [item[0].lower() for item in cursor.description], row
                    )} for row in cursor.fetchall()]
            finally:
                connection.close()
        else:
            from backend.core import store

            placeholders = ",".join("?" for _ in valid_regions)
            region_sql = f" AND o.region IN ({placeholders})" if valid_regions else ""
            store.initialize()
            with store.connect() as connection:
                rows = [dict(row) for row in connection.execute(
                    """SELECT p.name,o.region,SUM(ol.qty) units,
                              ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) revenue
                       FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
                       JOIN variants v ON v.variant_id=ol.variant_id
                       JOIN products p ON p.sku=v.sku
                       WHERE o.order_date >= '2026-09-01'""" + region_sql +
                    " GROUP BY p.name,o.region ORDER BY revenue DESC LIMIT 5",
                    valid_regions,
                ).fetchall()]
        return {"top_movers": rows, "regions": valid_regions,
                "window": "2026-09-01 through 2026-09-29",
                "provenance": ["orders", "order_lines", "variants", "products"]}

    @staticmethod
    def render_result(question: str, result: dict[str, Any], *, governed: bool = True) -> str:
        """Turn deterministic query results into a concise, evidence-bearing answer."""
        text = question.lower()
        if "profit" in text or "margin" in text:
            rows = result.get("rows", [])
            metric = result.get("metric", "net revenue") if governed else "net revenue (naive proxy)"
            ranked = sorted(rows, key=lambda row: row.get("gross_margin" if governed else "net_revenue", 0), reverse=True)
            body = "\n".join(
                f"- **{row['region']}** — £{row.get('gross_margin' if governed else 'net_revenue', 0):,.0f} "
                + (f"gross margin ({row.get('margin_percent', 0)}%)" if governed else "net revenue")
                for row in ranked[:4]
            )
            return f"## {'Governed' if governed else 'Ungoverned'} profitability answer\n\nMetric: `{metric}`.\n\n{body}"
        if "thermacore" in text and any(term in text for term in ("stock", "size", "low", "available", "inventory", "region")):
            rows = result.get("rows", [])
            totals: dict[str, int] = {}
            for row in rows:
                totals[row["size"]] = totals.get(row["size"], 0) + int(row["on_hand"])
            ranked = sorted(totals.items(), key=lambda item: item[1])
            low = ", ".join(f"**{size}: {units:,}**" for size, units in ranked[:3])
            high = ", ".join(f"{size}: {units:,}" for size, units in ranked[-2:][::-1])
            return ("## ThermaCore size availability\n\n"
                    f"The lowest aggregate size positions are {low} units across regions. "
                    f"The deepest positions are {high}.\n\n"
                    "The regional distribution still shows the planted M/L pressure in key locations; "
                    "open the data explorer on `inventory` for the row-level allocations.")
        if "warm" in text and ("spike" in text or "trend" in text):
            internal = result.get("internal", {})
            return ("## WarmLayer demand signal\n\n"
                    f"**{internal.get('last_7d_units', 0):,} units** sold in the last seven days, "
                    f"**{internal.get('change_percent', 0):+d}%** against the prior weekly baseline. "
                    "No internal promotion was detected; governed weather evidence is consistent with the increase, "
                    "but does not prove causation.")
        if "customer" in text or "return" in text:
            returns = result.get("returns", [])
            body = "\n".join(f"- **{row['product_line']}** — {row['returned_lines']:,} returned lines; {row['size_returns']:,} size-related."
                             for row in returns[:4])
            return f"## Returns context\n\n{body}\n\nOnly synthetic, pseudonymous customer aggregates were used."
        if "hello" in text or re.search(r"\bhi\b", text):
            return ("Hi — I’m ERPA. I can inspect Kata products and live inventory, explain demand signals, "
                    "compare regional profitability, prepare the morning brief, or show which memories and skills informed an answer.")
        if "news" in text or "headline" in text:
            return ("## External news access\n\n"
                    "I can’t retrieve open-ended live headlines in this local teaching mirror, so I won’t invent a latest-news answer. "
                    "The live harness only reads dated external signals after governed ingestion; for this dataset, try "
                    "**“Why did WarmLayer spike in the UK?”** to inspect the approved weather signal and its provenance.")
        if ((any(term in text for term in ("how many", "how much", "count")) and "product" in text)
                or (any(term in text for term in ("highest", "most", "largest", "total"))
                    and any(term in text for term in ("stock", "inventory")))):
            rows = result.get("top_stocked_products", [])
            if any(term in text for term in ("how many", "how much", "count")) and "product" in text:
                return ("## Catalog size\n\n"
                        f"Kata has **{result.get('product_count', 0):,} products** and "
                        f"**{result.get('variant_count', 0):,} sellable variants**, with "
                        f"**{result.get('available_units', 0):,} available units** in the current inventory snapshot.\n\n"
                        "Sources: `products`, `variants`, `inventory`.")
            body = "\n".join(
                f"- **{row['name']}** (`{row['sku']}`) — {int(row['available']):,} available units."
                for row in rows
            )
            return ("## Highest available stock\n\n"
                    f"{body}\n\nAcross the catalog there are **{result.get('available_units', 0):,} available units**. "
                    "Availability is on-hand less reserved stock.")
        if any(term in text for term in ("trend", "demand", "top seller", "best seller", "performance", "performing")):
            movers = result.get("top_movers", [])
            requested_regions = [region for region in ("UK", "EU", "US", "JP", "SEA") if region.lower() in text]
            if requested_regions:
                movers = [row for row in movers if row.get("region") in requested_regions]
            body = "\n".join(
                f"- **{row['name']} · {row['region']}** — {row['units']:,} units and £{row['revenue']:,.0f} net revenue."
                for row in movers[:4]
            )
            if body:
                scope = f" for {' + '.join(requested_regions)}" if requested_regions else ""
                return f"## Demand performance{scope}\n\n{body}\n\nRanked from governed order-line revenue in the current review window."
            return "## Demand performance\n\nNo qualifying mover matched that region in the current governed window."
        # The semantic fallback is deliberately a useful attention answer rather than
        # the former placeholder string.
        restock = result.get("restock", [])
        movers = result.get("top_movers", [])
        lines = ["## What needs attention"]
        if restock:
            lines.extend(["", "### Inventory", *[
                f"- **{row['name']} · {row['city']} · {row['size']}** — {row['on_hand']} on hand; recommend {row['recommended_qty']} units."
                for row in restock[:3]
            ]])
        if movers:
            lines.extend(["", "### Demand", *[
                f"- **{row['name']} · {row['region']}** — {row['units']:,} units / £{row['revenue']:,.0f} revenue."
                for row in movers[:3]
            ]])
        if len(lines) == 1:
            lines.extend(["", "I found no matching exception in the governed scope. Try naming a product line, region, stock, returns, demand, profit, or margin."])
        return "\n".join(lines)

    def compare(self, question: str) -> dict[str, Any]:
        """Run a naive schema-only interpretation beside the governed semantic path."""
        text = question.lower()
        governed = self.ask(question)
        if "profit" in text or "margin" in text:
            # Both sides query real rows; only the semantic path applies the canonical
            # ranking definition and relationship hints.
            raw_result = self.data.profitability()
            raw_context = {
                "interpretation": "profit ≈ net revenue",
                "metric": "SUM(qty × ticket price × (1-discount))",
                "relationships": ["orders → order_lines → variants → products"],
                "warning": "Unit cost and approved metric comments were not consulted.",
            }
        else:
            raw_result = governed["result"]
            raw_context = {
                "interpretation": "literal keyword-to-table matching",
                "matched_tables": self.search_catalog(question, 2),
                "warning": "No glossary aliases, governed hints, comments or workload facts were applied.",
            }
        return {
            "query": question,
            "without_semantic_layer": {
                "answer": self.render_result(question, raw_result, governed=False),
                "context": raw_context,
                "result": raw_result,
            },
            "with_semantic_layer": {
                "answer": self.render_result(question, governed["result"], governed=True),
                "context": governed["semantic_context"],
                "result": governed["result"],
            },
        }

    def execute_read_only(self, sql: str, params: tuple = ()) -> dict:
        return self.data.query_read_only(sql, params)


semantic_layer = SemanticLayer()
