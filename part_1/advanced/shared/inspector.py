"""Reusable LLM-context and read-only data explorer for advanced appbooks.

The browser receives only explicitly assembled model context and read-only rows.
It never receives provider credentials, hidden environment variables, or private
reasoning. Each app supplies its own runtime factory and data sources while this
module keeps the inspection shape consistent across the advanced section.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
from array import array
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from fastapi import APIRouter, HTTPException, Query


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
_SENSITIVE_COLUMN = re.compile(
    r"(?:password|passwd|secret|token|credential|api[_-]?key|private[_-]?key)", re.I
)
_SENSITIVE_ENV = re.compile(
    r"(?:password|passwd|secret|token|credential|api[_-]?key|private[_-]?key)", re.I
)


def _redact_text(value: str) -> str:
    rendered = str(value)
    for key, secret in os.environ.items():
        if _SENSITIVE_ENV.search(key) and len(secret) >= 8:
            rendered = rendered.replace(secret, "<redacted>")
    return rendered


def _json_value(value: Any, *, column: str = "") -> Any:
    if _SENSITIVE_COLUMN.search(column):
        return "<redacted>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return _redact_text(value) if isinstance(value, str) else value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        preview = base64.b64encode(bytes(value[:36])).decode("ascii")
        return f"<BINARY {len(value)} bytes · {preview}{'…' if len(value) > 36 else ''}>"
    if isinstance(value, (array, list, tuple)):
        values = list(value)
        if len(values) > 24 and all(isinstance(item, (int, float)) for item in values[:24]):
            return {
                "type": "vector",
                "dimensions": len(values),
                "preview": [round(float(item), 5) for item in values[:8]],
            }
        return [_json_value(item) for item in values]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item, column=str(key)) for key, item in value.items()}
    if hasattr(value, "read"):
        loaded = value.read()
        if isinstance(loaded, str) and len(loaded) > 4_000:
            return _redact_text(loaded[:4_000]) + "…"
        return _json_value(loaded, column=column)
    return _redact_text(str(value))


def _safe_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {str(key): _json_value(value, column=str(key)) for key, value in row.items()}
        for row in rows
    ]


def context_window(
    sections: Sequence[Mapping[str, Any]],
    *,
    provider: str,
    model: str,
    phase: str,
    actual_model_call: bool,
    max_tokens: int | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Normalize inspectable prompt sections and calculate a conservative budget."""

    normalized: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        content = section.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(_json_value(content), indent=2, ensure_ascii=False)
        content = _redact_text(content)
        characters = len(content)
        normalized.append(
            {
                "id": str(section.get("id") or f"section-{index + 1}"),
                "title": str(section.get("title") or f"Section {index + 1}"),
                "kind": str(section.get("kind") or "context"),
                "source": str(section.get("source") or "harness"),
                "included": bool(section.get("included", True)),
                "content": content,
                "characters": characters,
                "estimated_tokens": max(1, (characters + 3) // 4) if content else 0,
            }
        )
    used = sum(item["estimated_tokens"] for item in normalized if item["included"])
    return {
        "ready": True,
        "phase": phase,
        "provider": provider,
        "model": model,
        "actual_model_call": actual_model_call,
        "claim_boundary": (
            "Exact assembled input sections; private chain-of-thought is never captured."
            if actual_model_call
            else "No model call is represented by this view."
        ),
        "sections": normalized,
        "section_count": len(normalized),
        "estimated_tokens": used,
        "max_tokens": max_tokens,
        "utilization": round(used / max_tokens, 4) if max_tokens else None,
        "note": note,
    }


class InspectorDataSource(Protocol):
    source_id: str
    label: str
    kind: str

    def tables(self) -> list[dict[str, Any]]: ...

    def rows(self, table: str, *, limit: int, offset: int) -> dict[str, Any]: ...


@dataclass
class JsonDataSource:
    """A table-shaped view over in-memory runtime records."""

    source_id: str
    label: str
    provider: Callable[[], Mapping[str, Sequence[Mapping[str, Any]]]]
    kind: str = "runtime snapshot"

    def _data(self) -> dict[str, list[dict[str, Any]]]:
        return {
            str(name): _safe_rows(rows)
            for name, rows in self.provider().items()
            if _IDENTIFIER.fullmatch(str(name))
        }

    def tables(self) -> list[dict[str, Any]]:
        result = []
        for name, rows in sorted(self._data().items()):
            column_names = sorted({key for row in rows for key in row})
            result.append(
                {
                    "name": name,
                    "row_count": len(rows),
                    "columns": [
                        {"name": column, "type": "JSON", "nullable": True, "primary_key": False}
                        for column in column_names
                    ],
                    "primary_keys": [],
                }
            )
        return result

    def rows(self, table: str, *, limit: int, offset: int) -> dict[str, Any]:
        data = self._data()
        if table not in data:
            raise HTTPException(404, "Table is not available in this data source")
        rows = data[table]
        return {
            "source": self.source_id,
            "table": table,
            "row_count": len(rows),
            "offset": offset,
            "limit": limit,
            "rows": rows[offset : offset + limit],
        }


@dataclass
class SQLiteDataSource:
    source_id: str
    label: str
    path: Path
    kind: str = "SQLite ledger"

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise HTTPException(404, f"Data source {self.label} has not been created yet")
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _table_names(self, connection: sqlite3.Connection) -> list[str]:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            if _IDENTIFIER.fullmatch(str(row[0]))
        ]

    def tables(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._connect() as connection:
            result = []
            for table in self._table_names(connection):
                columns = [
                    {
                        "name": str(row[1]),
                        "type": str(row[2] or "ANY"),
                        "nullable": not bool(row[3]),
                        "primary_key": bool(row[5]),
                    }
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                ]
                count = int(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
                result.append(
                    {
                        "name": table,
                        "row_count": count,
                        "columns": columns,
                        "primary_keys": [item["name"] for item in columns if item["primary_key"]],
                    }
                )
        return result

    def rows(self, table: str, *, limit: int, offset: int) -> dict[str, Any]:
        if not _IDENTIFIER.fullmatch(table):
            raise HTTPException(400, "Invalid table identifier")
        with self._connect() as connection:
            if table not in self._table_names(connection):
                raise HTTPException(404, "Table is not available in this data source")
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            values = connection.execute(
                f'SELECT * FROM "{table}" LIMIT ? OFFSET ?', (limit, offset)
            ).fetchall()
            rows = _safe_rows(dict(row) for row in values)
        return {
            "source": self.source_id,
            "table": table,
            "row_count": count,
            "offset": offset,
            "limit": limit,
            "rows": rows,
        }


@dataclass
class OracleDataSource:
    source_id: str
    label: str
    pool: Any
    kind: str = "Oracle application schema"
    table_prefixes: tuple[str, ...] = ()

    def _allowed(self, name: str) -> bool:
        if not _IDENTIFIER.fullmatch(name) or name.startswith("BIN$"):
            return False
        return not self.table_prefixes or name.startswith(self.table_prefixes)

    def _names(self, connection: Any) -> list[str]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM user_tables ORDER BY table_name")
            return [str(row[0]) for row in cursor.fetchall() if self._allowed(str(row[0]))]

    def tables(self) -> list[dict[str, Any]]:
        with self.pool.acquire() as connection:
            names = self._names(connection)
            if not names:
                return []
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name,column_name,data_type,nullable,column_id "
                    "FROM user_tab_columns ORDER BY table_name,column_id"
                )
                columns_by_table: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
                for table_name, column_name, data_type, nullable, _ in cursor.fetchall():
                    if table_name in columns_by_table:
                        columns_by_table[str(table_name)].append(
                            {
                                "name": str(column_name),
                                "type": str(data_type),
                                "nullable": str(nullable) == "Y",
                                "primary_key": False,
                            }
                        )
                cursor.execute(
                    """SELECT cols.table_name,cols.column_name,cols.position
                       FROM user_constraints cons
                       JOIN user_cons_columns cols ON cons.constraint_name=cols.constraint_name
                       WHERE cons.constraint_type='P'
                       ORDER BY cols.table_name,cols.position"""
                )
                primary: dict[str, list[tuple[int, str]]] = {}
                for table_name, column_name, position in cursor.fetchall():
                    primary.setdefault(str(table_name), []).append((int(position), str(column_name)))
            result = []
            for name in names:
                primary_names = [column for _, column in sorted(primary.get(name, []))]
                for column in columns_by_table[name]:
                    column["primary_key"] = column["name"] in primary_names
                result.append(
                    {
                        "name": name,
                        "row_count": None,
                        "columns": columns_by_table[name],
                        "primary_keys": primary_names,
                    }
                )
        return result

    def rows(self, table: str, *, limit: int, offset: int) -> dict[str, Any]:
        table = table.upper()
        if not self._allowed(table):
            raise HTTPException(400, "Invalid table identifier")
        with self.pool.acquire() as connection:
            names = self._names(connection)
            if table not in names:
                raise HTTPException(404, "Table is not available in this data source")
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT cols.column_name,cols.position
                       FROM user_constraints cons
                       JOIN user_cons_columns cols ON cons.constraint_name=cols.constraint_name
                       WHERE cons.constraint_type='P' AND cols.table_name=:table_name
                       ORDER BY cols.position""",
                    {"table_name": table},
                )
                primary = [str(row[0]) for row in cursor.fetchall()]
                order = ",".join(f'"{name}"' for name in primary) if primary else "ROWID"
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = int(cursor.fetchone()[0])
                cursor.execute(
                    f'SELECT * FROM "{table}" ORDER BY {order} '
                    "OFFSET :row_offset ROWS FETCH NEXT :row_limit ROWS ONLY",
                    {"row_offset": offset, "row_limit": limit},
                )
                columns = [str(item[0]) for item in cursor.description]
                rows = _safe_rows(
                    {name: value for name, value in zip(columns, row)}
                    for row in cursor.fetchall()
                )
        return {
            "source": self.source_id,
            "table": table,
            "row_count": count,
            "offset": offset,
            "limit": limit,
            "rows": rows,
        }


def build_inspector_router(
    *,
    runtime_factory: Callable[[], Any],
    source_factory: Callable[[Any], Sequence[InspectorDataSource]],
    context_factory: Callable[[Any], Mapping[str, Any]] | None = None,
) -> APIRouter:
    """Build the common API mounted before each app's static frontend."""

    router = APIRouter(prefix="/api/inspector", tags=["inspector"])

    def sources() -> dict[str, InspectorDataSource]:
        runtime = runtime_factory()
        return {source.source_id: source for source in source_factory(runtime)}

    @router.get("/status")
    async def status() -> dict[str, Any]:
        runtime = runtime_factory()
        available = list(source_factory(runtime))
        return {
            "ready": True,
            "context_endpoint": "/api/inspector/context",
            "data_access": "read-only, schema-scoped, sensitive-column redaction",
            "sources": [
                {"id": item.source_id, "label": item.label, "kind": item.kind}
                for item in available
            ],
        }

    @router.get("/context")
    async def context() -> Mapping[str, Any]:
        runtime = runtime_factory()
        if context_factory is not None:
            return context_factory(runtime)
        method = getattr(runtime, "context_window", None)
        if callable(method):
            return method()
        return context_window(
            [{"title": "Runtime status", "kind": "control", "content": getattr(runtime, "status")()}],
            provider="none",
            model="none",
            phase="awaiting_run",
            actual_model_call=False,
        )

    @router.get("/sources")
    async def list_sources() -> dict[str, Any]:
        resolved = sources()
        payload = []
        for source in resolved.values():
            tables = source.tables()
            payload.append(
                {
                    "id": source.source_id,
                    "label": source.label,
                    "kind": source.kind,
                    "table_count": len(tables),
                    "tables": tables,
                }
            )
        return {"sources": payload}

    @router.get("/sources/{source_id}/tables/{table}/rows")
    async def table_rows(
        source_id: str,
        table: str,
        limit: int = Query(40, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        resolved = sources()
        source = resolved.get(source_id)
        if source is None:
            raise HTTPException(404, "Unknown inspector data source")
        return source.rows(table, limit=limit, offset=offset)

    return router


__all__ = [
    "JsonDataSource",
    "OracleDataSource",
    "SQLiteDataSource",
    "build_inspector_router",
    "context_window",
]
