"""Idempotently load the generated CSV set into Oracle using thin mode."""
from __future__ import annotations

import csv
import os
from pathlib import Path

import oracledb

HERE = Path(__file__).resolve().parents[1]
CSV_DIR = HERE / "out" / "csv"
ORDER = ("products", "variants", "locations", "customers", "suppliers", "product_suppliers",
         "orders", "order_lines", "returns", "inventory", "purchase_orders")
KEYS = {"products": "sku", "variants": "variant_id", "locations": "location_id", "customers": "customer_id",
        "suppliers": "supplier_id", "product_suppliers": "sku", "orders": "order_id", "order_lines": "line_id",
        "returns": "return_id", "purchase_orders": "po_id"}


def main() -> None:
    conn = oracledb.connect(user=os.environ["ORA_AGENT_USER"], password=os.environ["ORA_AGENT_PWD"],
                           dsn=os.environ["ORA_DSN"])
    with conn.cursor() as cursor:
        cursor.execute("ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD'")
        for table in ORDER:
            path = CSV_DIR / f"{table}.csv"
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle); rows = list(reader)
            if not rows:
                continue
            columns = reader.fieldnames or []
            oracle_columns = [
                "collection" if column == "collection_name" else
                "size_code" if table == "variants" and column == "size" else column
                for column in columns
            ]
            placeholders = ",".join(f":{i+1}" for i in range(len(columns)))
            if table in KEYS:
                key = KEYS[table]; key_pos = columns.index(key)
                for row in rows:
                    values = [row[column] or None for column in columns]
                    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {key}=:1", [values[key_pos]])
                    if cursor.fetchone()[0] == 0:
                        cursor.execute(f"INSERT INTO {table} ({','.join(oracle_columns)}) VALUES ({placeholders})", values)
            else:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                present = cursor.fetchone()[0]
                if present == len(rows):
                    print(table, len(rows), "already present")
                    continue
                if present:
                    raise RuntimeError(f"{table} is partially loaded ({present}/{len(rows)}); inspect rather than resetting data")
                cursor.executemany(f"INSERT INTO {table} ({','.join(oracle_columns)}) VALUES ({placeholders})",
                                   [[row[column] or None for column in columns] for row in rows])
            conn.commit()
            print(table, len(rows))
    conn.close()


if __name__ == "__main__": main()
