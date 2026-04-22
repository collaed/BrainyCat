"""Custom columns — user-defined metadata fields stored in JSONB."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def create_column(name: str, label: str, datatype: str = "text") -> dict[str, Any]:
    """Create a custom column definition. Types: text, number, date, boolean, rating."""
    valid_types = {"text", "number", "date", "boolean", "rating"}
    if datatype not in valid_types:
        return {"error": f"invalid type, must be one of: {valid_types}"}
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
    """Set a custom column value for a book."""
    import json

    await execute(
        "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || jsonb_build_object($1, $2::text) WHERE id = $3",
        column_name,
        json.dumps(value) if not isinstance(value, str) else value,
        UUID(book_id),
    )
    return {"ok": True}


async def get_value(book_id: str, column_name: str) -> Any:
    row = await fetch_one("SELECT extra_metadata->$1 as val FROM books WHERE id = $2", column_name, UUID(book_id))
    return row["val"] if row else None
