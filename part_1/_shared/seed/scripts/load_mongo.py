"""Upsert the canonical CSV mirror used for Build A enterprise-data functions."""
from __future__ import annotations

import csv
import os
from pathlib import Path

from pymongo import MongoClient, ReplaceOne

HERE = Path(__file__).resolve().parents[1]
CSV_DIR = HERE / "out" / "csv"
KEYS = {"products": "sku", "variants": "variant_id", "locations": "location_id", "customers": "customer_id",
        "suppliers": "supplier_id", "product_suppliers": "sku", "orders": "order_id", "order_lines": "line_id",
        "returns": "return_id", "purchase_orders": "po_id"}


def main() -> None:
    db = MongoClient(os.environ["MONGODB_URI"])["erpa_enterprise_mirror"]
    for path in sorted(CSV_DIR.glob("*.csv")):
        table = path.stem
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        key = KEYS.get(table)
        if key:
            operations = [ReplaceOne({key: row[key]}, row, upsert=True) for row in rows]
        else:
            operations = [ReplaceOne({column: row[column] for column in row}, row, upsert=True) for row in rows]
        if operations:
            db[table].bulk_write(operations, ordered=False)
        print(table, len(rows))


if __name__ == "__main__": main()
