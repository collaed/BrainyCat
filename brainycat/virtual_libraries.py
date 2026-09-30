"""Virtual libraries — saved search queries as named views."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all


async def create_virtual_library(user_id: str, name: str, query: str, filters: dict | None = None) -> dict[str, Any]:
    """Create a virtual library (saved search)."""
    import json

    vid = uuid4()
    await execute(
        "INSERT INTO virtual_libraries (id, user_id, name, query, filters) VALUES ($1,$2,$3,$4,$5)",
        vid,
        UUID(user_id),
        name,
        query,
        json.dumps(filters or {}),
    )
    return {"id": str(vid), "name": name, "query": query}


async def list_virtual_libraries(user_id: str) -> list[dict[str, Any]]:
    """List a user's saved virtual libraries (saved searches).

    Called by GET /api/v1/virtual-libraries (brainycat/routes/admin.py).
    """
    rows = await fetch_all(
        "SELECT id, name, query, filters FROM virtual_libraries WHERE user_id = $1 ORDER BY name",
        UUID(user_id),
    )
    return [dict(r) for r in rows]


async def delete_virtual_library(vlib_id: str, user_id: str) -> dict[str, bool]:
    """Delete a virtual library owned by the given user.

    Called by DELETE /api/v1/virtual-libraries/{vlib_id} (brainycat/routes/admin.py).
    """
    await execute("DELETE FROM virtual_libraries WHERE id = $1 AND user_id = $2", UUID(vlib_id), UUID(user_id))
    return {"ok": True}
