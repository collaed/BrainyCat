"""Filename history — record before/after for every rename, compute alignment %."""

from __future__ import annotations

from difflib import SequenceMatcher
from uuid import UUID

from brainycat.db import execute, fetch_all


def compute_alignment(before: str, after: str) -> float:
    """Return 0–100 similarity between two filenames (ignoring extension)."""
    a = before.rsplit(".", 1)[0] if "." in before else before
    b = after.rsplit(".", 1)[0] if "." in after else after
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100, 1)


async def record_rename(book_id: str | UUID, operation: str, before: str, after: str) -> None:
    """Record a filename change with computed alignment."""
    pct = compute_alignment(before, after)
    await execute(
        "INSERT INTO filename_history (book_id, operation, filename_before, filename_after, alignment_pct) "
        "VALUES ($1, $2, $3, $4, $5)",
        UUID(str(book_id)), operation, before, after, pct,
    )


async def revert_rename(history_id: str | UUID) -> dict:
    """Revert a filename change — rename file back and update DB."""
    import os
    import shutil

    from brainycat.db import fetch_one

    row = await fetch_one(
        "SELECT h.*, bf.file_path FROM filename_history h "
        "JOIN book_files bf ON bf.book_id = h.book_id "
        "WHERE h.id = $1 AND NOT h.reverted ORDER BY bf.created_at LIMIT 1",
        UUID(str(history_id)),
    )
    if not row:
        return {"error": "not found or already reverted"}

    current_path = row["file_path"]
    old_name = row["filename_before"]
    new_path = os.path.join(os.path.dirname(current_path), old_name)

    if os.path.isfile(current_path) and not os.path.exists(new_path):
        shutil.move(current_path, new_path)
        await execute("UPDATE book_files SET file_path = $1, file_name = $2 WHERE book_id = $3",
                      new_path, old_name, row["book_id"])
        await execute("UPDATE filename_history SET reverted = true WHERE id = $1", UUID(str(history_id)))
        return {"ok": True, "reverted_to": old_name}

    return {"error": "file not found or target exists"}


async def get_history(limit: int = 100, sort_by: str = "created_at", order: str = "desc",
                      min_alignment: float | None = None, max_alignment: float | None = None) -> list[dict]:
    """Fetch filename history with optional alignment filtering."""
    allowed_sorts = {"created_at", "alignment_pct", "operation"}
    col = sort_by if sort_by in allowed_sorts else "created_at"
    direction = "ASC" if order.lower() == "asc" else "DESC"

    conditions = []
    params: list = []
    idx = 1

    if min_alignment is not None:
        conditions.append(f"h.alignment_pct >= ${idx}")
        params.append(min_alignment)
        idx += 1
    if max_alignment is not None:
        conditions.append(f"h.alignment_pct <= ${idx}")
        params.append(max_alignment)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = await fetch_all(
        f"SELECT h.*, b.title FROM filename_history h "
        f"JOIN books b ON b.id = h.book_id "
        f"{where} ORDER BY h.{col} {direction} LIMIT ${idx}",
        *params,
    )
    return [dict(r) for r in rows]
