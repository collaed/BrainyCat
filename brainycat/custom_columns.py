"""Custom columns — user-defined metadata fields with type validation and search.

Supports: text, number, date, boolean, rating (1-10), tags (comma-separated).
Stored in books.extra_metadata JSONB. Searchable via SQL JSONB operators.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one

VALID_TYPES = {"text", "number", "date", "boolean", "rating", "tags"}


def _validate_value(value: Any, datatype: str) -> tuple[Any, str | None]:
    """Validate and coerce a value to the column's type. Returns (value, error)."""
    if value is None:
        return None, None
    if datatype == "text":
        return str(value), None
    if datatype == "number":
        try:
            return float(value), None
        except (ValueError, TypeError):
            return None, f"expected number, got {type(value).__name__}"
    if datatype == "date":
        if isinstance(value, (date, datetime)):
            return value.isoformat(), None
        try:
            datetime.fromisoformat(str(value))
            return str(value), None
        except ValueError:
            return None, f"invalid date format: {value}"
    if datatype == "boolean":
        if isinstance(value, bool):
            return value, None
        if str(value).lower() in ("true", "1", "yes"):
            return True, None
        if str(value).lower() in ("false", "0", "no"):
            return False, None
        return None, f"expected boolean, got {value}"
    if datatype == "rating":
        try:
            r = float(value)
            if not 0 <= r <= 10:
                return None, "rating must be 0-10"
            return r, None
        except (ValueError, TypeError):
            return None, f"expected number 0-10, got {value}"
    if datatype == "tags":
        if isinstance(value, list):
            return value, None
        if isinstance(value, str):
            return [t.strip() for t in value.split(",") if t.strip()], None
        return None, f"expected list or comma-separated string, got {type(value).__name__}"
    return None, f"unknown type: {datatype}"


async def create_column(name: str, label: str, datatype: str = "text") -> dict[str, Any]:
    if datatype not in VALID_TYPES:
        return {"error": f"invalid type '{datatype}', must be one of: {sorted(VALID_TYPES)}"}
    if not name.isidentifier():
        return {"error": "name must be a valid identifier (letters, digits, underscores)"}
    await execute(
        "INSERT INTO custom_columns (name, label, datatype) VALUES ($1, $2, $3) ON CONFLICT (name) DO NOTHING",
        name,
        label,
        datatype,
    )
    return {"ok": True, "name": name, "label": label, "datatype": datatype}


async def list_columns() -> list[dict[str, Any]]:
    rows = await fetch_all("SELECT name, label, datatype FROM custom_columns ORDER BY name")
    return [dict(r) for r in rows]


async def set_value(book_id: str, column_name: str, value: Any) -> dict[str, Any]:
    col = await fetch_one("SELECT datatype FROM custom_columns WHERE name = $1", column_name)
    if not col:
        return {"error": f"column '{column_name}' not found"}

    validated, err = _validate_value(value, col["datatype"])
    if err:
        return {"error": err}

    await execute(
        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), $1, $2::jsonb) WHERE id = $3",
        f"{{{column_name}}}",
        json.dumps(validated),
        UUID(book_id),
    )
    return {"ok": True, "value": validated}


async def get_value(book_id: str, column_name: str) -> Any:
    row = await fetch_one(
        "SELECT extra_metadata->>$1 as val FROM books WHERE id = $2",
        column_name,
        UUID(book_id),
    )
    return row["val"] if row else None


async def search_by_column(column_name: str, value: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search books by custom column value."""
    col = await fetch_one("SELECT datatype FROM custom_columns WHERE name = $1", column_name)
    if not col:
        return []

    if col["datatype"] in ("text", "tags"):
        rows = await fetch_all(
            "SELECT id, title, extra_metadata->>$1 as col_value FROM books WHERE extra_metadata->>$1 ILIKE '%' || $2 || '%' LIMIT $3",
            column_name,
            value,
            limit,
        )
    else:
        rows = await fetch_all(
            "SELECT id, title, extra_metadata->>$1 as col_value FROM books WHERE extra_metadata->>$1 = $2 LIMIT $3",
            column_name,
            value,
            limit,
        )
    return [{"id": str(r["id"]), "title": r["title"], "value": r["col_value"]} for r in rows]
