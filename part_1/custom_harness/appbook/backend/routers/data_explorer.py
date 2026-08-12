"""Read-only database explorer, activity stream and transactional demo storefront."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from backend.config import settings
from backend.core import store
from backend.core.activity import activity
from backend.core.agent import get_graph
from backend.schemas import ChatReq, CheckoutReq

router = APIRouter(prefix="/api", tags=["data_explorer", "storefront"])
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
_AS_OF = date(2026, 9, 29)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, bytes):
        preview = base64.b64encode(value[:48]).decode("ascii")
        return f"<BLOB {len(value)} bytes · {preview}{'…' if len(value) > 48 else ''}>"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "read"):
        loaded = value.read()
        return _json_value(loaded)
    return str(value)


def _layer(table: str) -> str:
    name = table.lower()
    if name in {"products", "variants", "locations", "inventory", "customers", "orders", "order_lines", "returns", "suppliers", "product_suppliers", "purchase_orders", "custom_store_orders", "custom_store_order_lines", "erpa_store_orders", "erpa_store_order_lines"}:
        return "commerce"
    if "scratch" in name or "promotion" in name or "session" in name:
        return "working memory"
    if "memory" in name:
        return "memory"
    if "cache" in name:
        return "cache"
    if "checkpoint" in name or "write" in name or "blob" in name:
        return "orchestration"
    if "semantic" in name or "skill" in name or "tool" in name:
        return "semantic"
    return "harness"


def _local_tables() -> list[dict[str, Any]]:
    store.initialize()
    result = []
    with store.connect() as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        for name in names:
            columns = []
            primary_keys = []
            for row in connection.execute(f'PRAGMA table_info("{name}")'):
                column = {"name": row[1], "type": row[2] or "ANY", "nullable": not bool(row[3]), "primary_key": bool(row[5])}
                columns.append(column)
                if row[5]:
                    primary_keys.append((row[5], row[1]))
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            result.append({"name": name, "row_count": count, "columns": columns,
                           "primary_keys": [name for _, name in sorted(primary_keys)], "layer": _layer(name)})
    return result


def _live_tables() -> list[dict[str, Any]]:
    from backend.core.oracle_live import get_oracle_stack

    connection = get_oracle_stack().pool.acquire()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM user_tables ORDER BY table_name")
            names = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                """SELECT table_name,column_name,data_type,nullable,column_id
                   FROM user_tab_columns ORDER BY table_name,column_id"""
            )
            columns_by_table: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
            for table_name, column_name, data_type, nullable, _ in cursor.fetchall():
                if table_name in columns_by_table:
                    columns_by_table[table_name].append({"name": column_name.lower(), "type": data_type,
                                                         "nullable": nullable == "Y", "primary_key": False})
            cursor.execute(
                """SELECT cols.table_name,cols.column_name,cols.position
                   FROM user_constraints cons JOIN user_cons_columns cols
                     ON cons.constraint_name=cols.constraint_name
                   WHERE cons.constraint_type='P' ORDER BY cols.table_name,cols.position"""
            )
            primary: dict[str, list[tuple[int, str]]] = {}
            for table_name, column_name, position in cursor.fetchall():
                primary.setdefault(table_name, []).append((position, column_name.lower()))
            for table_name, items in primary.items():
                wanted = {name for _, name in items}
                for column in columns_by_table.get(table_name, []):
                    column["primary_key"] = column["name"] in wanted
            result = []
            for name in names:
                try:
                    cursor.execute(f'SELECT COUNT(*) FROM "{name}"')
                    count = int(cursor.fetchone()[0])
                except Exception:
                    count = -1
                result.append({"name": name.lower(), "row_count": count, "columns": columns_by_table[name],
                               "primary_keys": [column for _, column in primary.get(name, [])], "layer": _layer(name)})
            return result
    finally:
        connection.close()


def _tables() -> list[dict[str, Any]]:
    return _live_tables() if settings.live else _local_tables()


def _table_definition(table: str) -> dict[str, Any]:
    normalized = table.lower()
    if not _IDENTIFIER.fullmatch(table):
        raise HTTPException(400, "Invalid table identifier")
    for item in _tables():
        if item["name"].lower() == normalized:
            return item
    raise HTTPException(404, "Table is not available in the application schema")


@router.get("/data_explorer/status")
async def explorer_status():
    tables = _tables()
    return {"ready": True, "mode": settings.mode, "tables": len(tables),
            "rows": sum(max(0, item["row_count"]) for item in tables),
            "stream": "/api/data_explorer/activity", "access": "read-only allowlisted browser"}


@router.get("/data_explorer/tables")
async def tables():
    return {"mode": settings.mode, "tables": _tables()}


@router.get("/data_explorer/tables/{table}/rows")
async def table_rows(table: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    definition = _table_definition(table)
    primary_keys = definition["primary_keys"]
    if settings.live:
        from backend.core.oracle_live import get_oracle_stack

        physical = table.upper()
        order = ",".join(f'"{name.upper()}"' for name in primary_keys) if primary_keys else "ROWID"
        connection = get_oracle_stack().pool.acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT * FROM "{physical}" ORDER BY {order} OFFSET :1 ROWS FETCH NEXT :2 ROWS ONLY', [offset, limit])
                columns = [item[0].lower() for item in cursor.description]
                rows = [{name: _json_value(value) for name, value in zip(columns, row)} for row in cursor.fetchall()]
        finally:
            connection.close()
    else:
        order = ",".join(f'"{name}"' for name in primary_keys) if primary_keys else "rowid"
        with store.connect() as connection:
            cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY {order} LIMIT ? OFFSET ?', (limit, offset))
            rows = [{name: _json_value(row[name]) for name in row.keys()} for row in cursor.fetchall()]
    row_keys = ["|".join(str(row.get(key, "")) for key in primary_keys) if primary_keys else str(offset + index + 1)
                for index, row in enumerate(rows)]
    return {"table": definition["name"], "columns": definition["columns"], "primary_keys": primary_keys,
            "row_count": definition["row_count"], "offset": offset, "limit": limit, "rows": rows, "row_keys": row_keys}


@router.get("/data_explorer/activity/recent")
async def recent_activity(limit: int = Query(30, ge=1, le=100)):
    return {"events": activity.recent(limit)}


@router.get("/data_explorer/activity")
async def activity_stream(request: Request):
    async def generate():
        queue = activity.subscribe()
        try:
            yield {"event": "ready", "data": json.dumps({"status": "connected", "mode": settings.mode})}
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield {"event": "transaction", "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": json.dumps({"status": "alive"})}
        finally:
            activity.unsubscribe(queue)
    return EventSourceResponse(generate())


def _catalog_local() -> list[dict[str, Any]]:
    store.initialize()
    with store.connect() as connection:
        rows = connection.execute(
            """SELECT p.sku,p.name,p.product_line,p.category,p.collection_name AS collection,
                      p.season,p.base_price,p.fabric,p.is_core,
                      COUNT(DISTINCT v.variant_id) variant_count,
                      COALESCE(SUM(i.on_hand),0) total_stock,
                      COALESCE(SUM(i.reserved),0) reserved,
                      COALESCE(SUM(i.in_transit),0) in_transit,
                      GROUP_CONCAT(DISTINCT v.colour) colours,
                      GROUP_CONCAT(DISTINCT v.size) sizes
               FROM products p LEFT JOIN variants v ON v.sku=p.sku
               LEFT JOIN inventory i ON i.variant_id=v.variant_id
               GROUP BY p.sku,p.name,p.product_line,p.category,p.collection_name,p.season,
                        p.base_price,p.fabric,p.is_core ORDER BY p.category,p.name"""
        ).fetchall()
    return [{name: _json_value(row[name]) for name in row.keys()} for row in rows]


def _catalog_live() -> list[dict[str, Any]]:
    from backend.core.oracle_live import get_oracle_stack

    connection = get_oracle_stack().pool.acquire()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT p.sku,p.name,p.product_line,p.category,p.collection,p.season,p.base_price,
                          p.fabric,p.is_core,COUNT(DISTINCT v.variant_id) variant_count,
                          NVL(SUM(i.on_hand),0) total_stock,NVL(SUM(i.reserved),0) reserved,
                          NVL(SUM(i.in_transit),0) in_transit,
                          LISTAGG(DISTINCT v.colour,',') WITHIN GROUP (ORDER BY v.colour) colours,
                          LISTAGG(DISTINCT v.size_code,',') WITHIN GROUP (ORDER BY v.size_code) sizes
                   FROM products p LEFT JOIN variants v ON v.sku=p.sku
                   LEFT JOIN inventory i ON i.variant_id=v.variant_id
                   GROUP BY p.sku,p.name,p.product_line,p.category,p.collection,p.season,
                            p.base_price,p.fabric,p.is_core ORDER BY p.category,p.name"""
            )
            columns = [item[0].lower() for item in cursor.description]
            return [{name: _json_value(value) for name, value in zip(columns, row)} for row in cursor.fetchall()]
    finally:
        connection.close()


@router.get("/storefront/catalog")
async def storefront_catalog():
    products = _catalog_live() if settings.live else _catalog_local()
    categories = sorted({item["category"] for item in products})
    return {"as_of": _AS_OF.isoformat(), "currency": "GBP", "products": products,
            "categories": categories, "inventory_source": "Oracle AI Database" if settings.live else "SQLite teaching mirror"}


def _product_detail_local(sku: str) -> dict[str, Any] | None:
    store.initialize()
    with store.connect() as connection:
        product = connection.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        if not product:
            return None
        rows = connection.execute(
            """SELECT v.variant_id,v.size,v.colour,l.location_id,l.region,l.city,
                      i.on_hand,i.reserved,i.in_transit,i.reorder_point,i.snapshot_date
               FROM variants v JOIN inventory i ON i.variant_id=v.variant_id
               JOIN locations l ON l.location_id=i.location_id
               WHERE v.sku=? ORDER BY v.colour,v.size,l.region,l.city""", (sku,)
        ).fetchall()
    return {"product": dict(product), "inventory": [dict(row) for row in rows]}


def _product_detail_live(sku: str) -> dict[str, Any] | None:
    from backend.core.oracle_live import get_oracle_stack
    connection = get_oracle_stack().pool.acquire()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM products WHERE sku=:1", [sku])
            row = cursor.fetchone()
            if not row:
                return None
            columns = [item[0].lower() for item in cursor.description]
            product = {name: _json_value(value) for name, value in zip(columns, row)}
            cursor.execute(
                """SELECT v.variant_id,v.size_code AS size,v.colour,l.location_id,l.region,l.city,
                          i.on_hand,i.reserved,i.in_transit,i.reorder_point,i.snapshot_date
                   FROM variants v JOIN inventory i ON i.variant_id=v.variant_id
                   JOIN locations l ON l.location_id=i.location_id
                   WHERE v.sku=:1 ORDER BY v.colour,v.size_code,l.region,l.city""", [sku]
            )
            columns = [item[0].lower() for item in cursor.description]
            inventory = [{name: _json_value(value) for name, value in zip(columns, item)} for item in cursor.fetchall()]
    finally:
        connection.close()
    return {"product": product, "inventory": inventory}


@router.get("/storefront/products/{sku}")
async def storefront_product(sku: str):
    if not _IDENTIFIER.fullmatch(sku.replace("-", "")):
        raise HTTPException(400, "Invalid product identifier")
    detail = _product_detail_live(sku) if settings.live else _product_detail_local(sku)
    if not detail:
        raise HTTPException(404, "Product not found")
    available = sum(max(0, int(row["on_hand"]) - int(row["reserved"])) for row in detail["inventory"])
    by_size: dict[str, int] = {}
    by_region: dict[str, int] = {}
    for row in detail["inventory"]:
        units = max(0, int(row["on_hand"]) - int(row["reserved"]))
        by_size[row["size"]] = by_size.get(row["size"], 0) + units
        by_region[row["region"]] = by_region.get(row["region"], 0) + units
    return {**detail, "available": available, "by_size": by_size, "by_region": by_region,
            "colours": sorted({row["colour"] for row in detail["inventory"]}),
            "snapshot_date": max(str(row["snapshot_date"]) for row in detail["inventory"])}


def _checkout_local(req: CheckoutReq) -> dict[str, Any]:
    store.initialize()
    order_id = f"WEB-{uuid.uuid4().hex[:12].upper()}"
    purchased = []
    connection = store.connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO custom_store_orders VALUES (?,?,?,?,?,?,?,?)",
            (order_id, req.customer_name, req.email, _AS_OF.isoformat(), "UK", "web", "processing", 0.0),
        )
        for request_line in req.lines:
            row = connection.execute(
                """SELECT v.variant_id,i.location_id,i.snapshot_date,i.on_hand,i.reserved,p.base_price,p.name
                   FROM products p JOIN variants v ON v.sku=p.sku JOIN inventory i ON i.variant_id=v.variant_id
                   WHERE p.sku=? AND (i.on_hand-i.reserved)>=?
                     AND (i.on_hand<i.reorder_point OR i.on_hand-? >= i.reorder_point)
                   ORDER BY CASE WHEN i.location_id='UK-LON-DC' THEN 0 ELSE 1 END,(i.on_hand-i.reserved) DESC LIMIT 1""",
                (request_line.sku, request_line.quantity, request_line.quantity),
            ).fetchone()
            if not row:
                raise ValueError(f"Insufficient available inventory for {request_line.sku}")
            connection.execute(
                "UPDATE inventory SET on_hand=on_hand-? WHERE variant_id=? AND location_id=? AND snapshot_date=?",
                (request_line.quantity, row[0], row[1], row[2]),
            )
            cursor = connection.execute(
                """INSERT INTO custom_store_order_lines(order_id,sku,variant_id,location_id,qty,unit_price)
                   VALUES (?,?,?,?,?,?)""",
                (order_id, request_line.sku, row[0], row[1], request_line.quantity, row[5]),
            )
            purchased.append({"line_id": cursor.lastrowid, "sku": request_line.sku, "name": row[6],
                              "variant_id": row[0], "location_id": row[1], "quantity": request_line.quantity,
                              "unit_price": row[5]})
        total = round(sum(item["quantity"] * item["unit_price"] for item in purchased), 2)
        connection.execute("UPDATE custom_store_orders SET status='confirmed',total=? WHERE order_id=?", (total, order_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"order_id": order_id, "status": "confirmed", "customer": req.customer_name,
            "items": purchased, "total": total}


def _checkout_live(req: CheckoutReq) -> dict[str, Any]:
    from backend.core.oracle_live import get_oracle_stack

    order_id = f"WEB-{uuid.uuid4().hex[:12].upper()}"
    purchased = []
    connection = get_oracle_stack().pool.acquire()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO erpa_store_orders
                     (order_id,customer_name,email,order_date,region,channel,status,total)
                   VALUES (:1,:2,:3,:4,'UK','web','processing',0)""",
                [order_id, req.customer_name, req.email, _AS_OF],
            )
            cursor.execute("SELECT NVL(MAX(line_id),0)+1 FROM erpa_store_order_lines")
            next_line = int(cursor.fetchone()[0])
            for request_line in req.lines:
                cursor.execute(
                    """SELECT v.variant_id,i.location_id,i.snapshot_date,i.on_hand,i.reserved,p.base_price,p.name
                       FROM products p JOIN variants v ON v.sku=p.sku JOIN inventory i ON i.variant_id=v.variant_id
                       WHERE p.sku=:sku AND (i.on_hand-i.reserved)>=:quantity
                         AND (i.on_hand<i.reorder_point OR i.on_hand-:quantity >= i.reorder_point)
                       ORDER BY CASE WHEN i.location_id='UK-LON-DC' THEN 0 ELSE 1 END,(i.on_hand-i.reserved) DESC""",
                    {"sku": request_line.sku, "quantity": request_line.quantity},
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError(f"Insufficient available inventory for {request_line.sku}")
                cursor.execute(
                    """SELECT on_hand FROM inventory WHERE variant_id=:1 AND location_id=:2 AND snapshot_date=:3 FOR UPDATE""",
                    [row[0], row[1], row[2]],
                )
                locked = int(cursor.fetchone()[0])
                if locked - int(row[4]) < request_line.quantity:
                    raise ValueError(f"Inventory changed while checking out {request_line.sku}; please retry")
                cursor.execute(
                    "UPDATE inventory SET on_hand=on_hand-:1 WHERE variant_id=:2 AND location_id=:3 AND snapshot_date=:4",
                    [request_line.quantity, row[0], row[1], row[2]],
                )
                cursor.execute(
                    """INSERT INTO erpa_store_order_lines
                         (line_id,order_id,sku,variant_id,location_id,qty,unit_price)
                       VALUES (:1,:2,:3,:4,:5,:6,:7)""",
                    [next_line, order_id, request_line.sku, row[0], row[1], request_line.quantity, row[5]],
                )
                purchased.append({"line_id": next_line, "sku": request_line.sku, "name": row[6],
                                  "variant_id": row[0], "location_id": row[1], "quantity": request_line.quantity,
                                  "unit_price": _json_value(row[5])})
                next_line += 1
            total = round(sum(item["quantity"] * item["unit_price"] for item in purchased), 2)
            cursor.execute("UPDATE erpa_store_orders SET status='confirmed',total=:1 WHERE order_id=:2", [total, order_id])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"order_id": order_id, "status": "confirmed", "customer": req.customer_name,
            "items": purchased, "total": total}


@router.post("/storefront/checkout")
async def checkout(req: CheckoutReq):
    try:
        result = _checkout_live(req) if settings.live else _checkout_local(req)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return result


@router.post("/storefront/chat")
async def storefront_chat(req: ChatReq):
    if settings.live:
        return get_graph().run(req.message, req.thread_id, session_id=req.session_id)
    return get_graph().run(req.message, req.thread_id)
