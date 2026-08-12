"""Build the deterministic Kata teaching dataset.

Local SQLite is the zero-credential workshop substrate.  ``--target csv`` emits the
same rows for loading into Oracle or MongoDB; the production adapters never maintain a
second set of fixtures.

Examples::

    python part_1/_shared/seed/generate_seed_data.py
    python part_1/_shared/seed/generate_seed_data.py --target csv
    python part_1/_shared/seed/generate_seed_data.py --validate-only
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent
ROOT = SHARED.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from catalogue import PRODUCT_LINES, REGIONS, SIZES, iter_products, variant_id  # noqa: E402

SEED = 20260929
AS_OF = date(2026, 9, 29)
OUT = HERE / "out"
DB_PATH = OUT / "kata.db"

SQLITE_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS products (
 sku TEXT PRIMARY KEY, name TEXT NOT NULL, product_line TEXT NOT NULL,
 category TEXT NOT NULL, collection_name TEXT, season TEXT, launch_date TEXT,
 base_price REAL NOT NULL, unit_cost REAL NOT NULL, fabric TEXT, is_core INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS variants (
 variant_id TEXT PRIMARY KEY, sku TEXT NOT NULL REFERENCES products(sku), size TEXT, colour TEXT);
CREATE TABLE IF NOT EXISTS locations (
 location_id TEXT PRIMARY KEY, region TEXT, type TEXT, country TEXT, city TEXT);
CREATE TABLE IF NOT EXISTS inventory (
 variant_id TEXT REFERENCES variants(variant_id), location_id TEXT REFERENCES locations(location_id),
 on_hand INTEGER, in_transit INTEGER, reserved INTEGER, reorder_point INTEGER, snapshot_date TEXT,
 PRIMARY KEY (variant_id, location_id, snapshot_date));
CREATE TABLE IF NOT EXISTS customers (
 customer_id TEXT PRIMARY KEY, region TEXT, segment TEXT, first_order_date TEXT,
 lifetime_orders INTEGER, lifetime_value REAL);
CREATE TABLE IF NOT EXISTS orders (
 order_id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers(customer_id),
 order_date TEXT, region TEXT, channel TEXT);
CREATE TABLE IF NOT EXISTS order_lines (
 line_id INTEGER PRIMARY KEY, order_id TEXT REFERENCES orders(order_id),
 variant_id TEXT REFERENCES variants(variant_id), qty INTEGER, unit_price REAL, discount REAL);
CREATE TABLE IF NOT EXISTS returns (
 return_id INTEGER PRIMARY KEY, order_id TEXT, variant_id TEXT, qty INTEGER,
 reason_code TEXT, return_date TEXT);
CREATE TABLE IF NOT EXISTS suppliers (
 supplier_id TEXT PRIMARY KEY, name TEXT, lead_time_days INTEGER, reliability_score REAL, minimum_order_qty INTEGER);
CREATE TABLE IF NOT EXISTS product_suppliers (
 sku TEXT PRIMARY KEY, supplier_id TEXT REFERENCES suppliers(supplier_id));
CREATE TABLE IF NOT EXISTS purchase_orders (
 po_id TEXT PRIMARY KEY, variant_id TEXT, location_id TEXT, qty INTEGER,
 raised_date TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS idx_orders_date_region ON orders(order_date, region);
CREATE INDEX IF NOT EXISTS idx_lines_variant ON order_lines(variant_id);
CREATE INDEX IF NOT EXISTS idx_variants_sku ON variants(sku);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshot ON inventory(snapshot_date, location_id);
CREATE TABLE IF NOT EXISTS seed_metadata (key TEXT PRIMARY KEY, value TEXT);
"""

LOCATIONS = (
    ("JP-TOK-DC", "JP", "DC", "Japan", "Tokyo"),
    ("UK-LON-DC", "UK", "DC", "United Kingdom", "London"),
    ("US-NJ-3PL", "US", "3PL", "United States", "New Jersey"),
    ("EU-BER-DC", "EU", "DC", "Germany", "Berlin"),
    ("EU-PAR-3PL", "EU", "3PL", "France", "Paris"),
    ("SEA-SIN-DC", "SEA", "DC", "Singapore", "Singapore"),
)

SUPPLIERS = (
    ("SUP-01", "Hikari Technical Textiles", 35, 0.96, 500),
    ("SUP-02", "NordWeave Manufacturing", 28, 0.91, 350),
    ("SUP-03", "Pearl River Basics", 42, 0.88, 750),
    ("SUP-04", "Izmir Cotton Works", 24, 0.94, 400),
    ("SUP-05", "Da Nang Performance", 31, 0.92, 450),
)


def _product_rows() -> tuple[list[tuple], list[tuple]]:
    products, variants = [], []
    for p in iter_products():
        products.append((p["sku"], p["name"], p["line"], p["category"], p["collection"],
                         p["season"], "2026-03-01", p["base_price"], p["unit_cost"],
                         p["fabric"], p["is_core"]))
        for colour in p["colours"]:
            for size in SIZES:
                variants.append((variant_id(p["sku"], colour, size), p["sku"], size, colour))
    return products, variants


def _seasonal_weight(line: str, region: str, day: date) -> float:
    winter = day.month in {10, 11, 12, 1, 2}
    if line in {"ThermaCore", "WarmLayer"}:
        return 2.8 if winter and region in {"UK", "EU", "JP"} else (0.7 if region == "SEA" else 1.0)
    if line == "AirLight":
        return 0.65 if winter and region in {"UK", "EU", "JP"} else 2.0
    return 1.0


def build_sqlite(path: Path = DB_PATH, *, force: bool = False) -> dict:
    """Idempotently create a complete local mirror and return row counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SQLITE_SCHEMA)
    current = conn.execute("SELECT value FROM seed_metadata WHERE key='version'").fetchone()
    if current and current[0] == "3" and not force:
        counts = validate(conn)
        conn.close()
        return counts

    for table in ("returns", "order_lines", "orders", "customers", "purchase_orders", "inventory",
                  "product_suppliers", "suppliers", "locations", "variants", "products", "seed_metadata"):
        conn.execute(f"DELETE FROM {table}")

    rng = random.Random(SEED)
    products, variants = _product_rows()
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)", products)
    conn.executemany("INSERT INTO variants VALUES (?,?,?,?)", variants)
    conn.executemany("INSERT INTO locations VALUES (?,?,?,?,?)", LOCATIONS)
    conn.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?)", SUPPLIERS)
    conn.executemany("INSERT INTO product_suppliers VALUES (?,?)",
                     [(p[0], SUPPLIERS[i % len(SUPPLIERS)][0]) for i, p in enumerate(products)])

    # Five thousand synthetic, pseudonymous customers. No names, email or PII.
    customers = []
    for i in range(1, 5001):
        region = rng.choices(REGIONS, [17, 18, 25, 25, 15])[0]
        orders = max(1, int(rng.expovariate(0.42)))
        segment = "vip" if orders >= 8 else "repeat" if orders >= 2 else "new"
        first = AS_OF - timedelta(days=rng.randint(30, 548))
        customers.append((f"CUS-{i:05d}", region, segment, first.isoformat(), orders, round(orders * rng.uniform(38, 94), 2)))
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

    product_by_sku = {p[0]: p for p in products}
    variants_by_line: dict[str, list[tuple]] = {line.name: [] for line in PRODUCT_LINES}
    for v in variants:
        variants_by_line[product_by_sku[v[1]][2]].append(v)

    order_rows, line_rows, return_rows = [], [], []
    line_id = return_id = 0
    start = AS_OF - timedelta(days=547)
    lines = [line.name for line in PRODUCT_LINES]
    for order_no in range(1, 40001):
        customer = customers[(order_no * 37) % len(customers)]
        region = customer[1]
        day = start + timedelta(days=rng.randrange(548))
        # The final week UK cold-snap signal is deliberately strongest for WarmLayer.
        weights = [_seasonal_weight(name, region, day) for name in lines]
        if region == "UK" and 0 <= (AS_OF - day).days <= 9:
            weights[lines.index("WarmLayer")] *= 8.0
        count = 3 if order_no <= 10000 else 2  # exactly 90,000 order lines
        oid = f"ORD-{order_no:06d}"
        order_rows.append((oid, customer[0], day.isoformat(), region, rng.choice(("web", "app", "store"))))
        for _ in range(count):
            line = rng.choices(lines, weights=weights)[0]
            v = rng.choice(variants_by_line[line])
            product = product_by_sku[v[1]]
            # EU produces healthy volume but weak margin through excessive discounting.
            discount = rng.uniform(0.24, 0.42) if region == "EU" else rng.uniform(0.0, 0.12)
            qty = 2 if rng.random() < 0.08 else 1
            line_id += 1
            line_rows.append((line_id, oid, v[0], qty, product[7], round(discount, 2)))
            return_probability = 0.27 if product[2] == "TrueDenim" else 0.045
            if rng.random() < return_probability:
                return_id += 1
                reason = "size" if product[2] == "TrueDenim" else rng.choice(("quality", "changed_mind", "damaged"))
                return_rows.append((return_id, oid, v[0], 1, reason, min(AS_OF, day + timedelta(days=7)).isoformat()))
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", order_rows)
    conn.executemany("INSERT INTO order_lines VALUES (?,?,?,?,?,?)", line_rows)
    conn.executemany("INSERT INTO returns VALUES (?,?,?,?,?,?)", return_rows)

    inventory_rows = []
    low = {
        (variant_id("KTA-THC-01", "Black", "M"), "EU-BER-DC"): (4, 28),
        (variant_id("KTA-PCT-01", "White", "M"), "UK-LON-DC"): (8, 35),
        (variant_id("KTA-DKN-03", "Cream", "L"), "EU-PAR-3PL"): (5, 30),
        (variant_id("KTA-FSH-01", "Black", "M"), "UK-LON-DC"): (6, 32),
    }
    for v in variants:
        for location in LOCATIONS:
            on_hand, reorder = rng.randint(45, 260), rng.randint(18, 38)
            # ThermaCore hero SKU has the apparel-authentic M/L sell-out and tails overhang.
            if v[1] == "KTA-THC-01":
                on_hand = {"XXS": 188, "XS": 142, "S": 72, "M": 7, "L": 5, "XL": 68, "XXL": 171}[v[2]]
                reorder = 4
            if (v[0], location[0]) in low:
                on_hand, reorder = low[(v[0], location[0])]
            inventory_rows.append((v[0], location[0], on_hand, rng.randint(0, 35), rng.randint(0, min(12, on_hand)), reorder, AS_OF.isoformat()))
    conn.executemany("INSERT INTO inventory VALUES (?,?,?,?,?,?,?)", inventory_rows)
    berlin_variant = variant_id("KTA-THC-01", "Black", "M")
    conn.execute("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?)",
                 ("PO-BER-THC-OPEN", berlin_variant, "EU-BER-DC", 600, (AS_OF - timedelta(days=1)).isoformat(), "open"))
    conn.executemany("INSERT INTO seed_metadata VALUES (?,?)", (
        ("version", "3"), ("seed", str(SEED)), ("as_of", AS_OF.isoformat()),
        ("generated_at", datetime.combine(AS_OF, datetime.min.time()).isoformat()),
    ))
    conn.commit()
    counts = validate(conn)
    conn.close()
    return counts


def validate(conn_or_path: sqlite3.Connection | Path = DB_PATH) -> dict:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    tables = ("products", "variants", "customers", "orders", "order_lines", "returns", "inventory")
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    assert counts["products"] == 60
    assert 800 <= counts["variants"] <= 1200
    assert counts["customers"] == 5000 and counts["orders"] == 40000 and counts["order_lines"] == 90000
    lows = conn.execute("SELECT COUNT(*) FROM inventory WHERE on_hand < reorder_point").fetchone()[0]
    open_po = conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE status='open'").fetchone()[0]
    assert lows == 4 and open_po == 1
    counts.update({"below_reorder": lows, "open_purchase_orders": open_po})
    if close:
        conn.close()
    return counts


def export_csv(db_path: Path = DB_PATH, out_dir: Path = OUT / "csv") -> None:
    build_sqlite(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    for table in ("products", "variants", "locations", "inventory", "customers", "orders",
                  "order_lines", "returns", "suppliers", "product_suppliers", "purchase_orders"):
        cursor = conn.execute(f"SELECT * FROM {table}")
        with (out_dir / f"{table}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(cursor)
    manifest = {"seed": SEED, "as_of": AS_OF.isoformat(), "tables": validate(conn)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("sqlite", "csv", "oracle", "mongo"), default="sqlite")
    parser.add_argument("--path", type=Path, default=DB_PATH)
    parser.add_argument("--force", action="store_true", help="rebuild the deterministic seed")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        counts = validate(args.path)
    else:
        counts = build_sqlite(args.path, force=args.force)
        if args.target in {"csv", "oracle", "mongo"}:
            export_csv(args.path)
            if args.target != "csv":
                print(f"{args.target}: generated portable CSV load set; use scripts/load_{args.target}.py with credentials")
    print(json.dumps({"database": str(args.path), **counts}, indent=2))


if __name__ == "__main__":
    main()
