"""Format stacking — detect same book in different formats and merge into one record.

Uses fingerprint overlap (content_chunks or book_fingerprints) to confirm
that two files are the same book before merging.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat import db


async def find_format_duplicates(limit: int = 50) -> list[dict[str, Any]]:
    """Find books that are likely the same content in different formats.

    Matches by: same ISBN, or title similarity > 0.8 with different formats.
    """
    # Same ISBN, different formats
    candidates = await db.fetch_all(
        """
        WITH book_fmts AS (
            SELECT b.id, b.title, b.isbn, array_agg(DISTINCT bf.format) as formats
            FROM books b JOIN book_files bf ON bf.book_id = b.id
            GROUP BY b.id
        )
        SELECT a.id as id_a, b.id as id_b, a.title as title_a, b.title as title_b,
               a.formats as fmts_a, b.formats as fmts_b, a.isbn
        FROM book_fmts a JOIN book_fmts b ON a.isbn = b.isbn AND a.id < b.id
        WHERE a.isbn IS NOT NULL AND a.formats != b.formats
        LIMIT $1
        """,
        limit,
    )
    if candidates:
        return [dict(r) for r in candidates]

    # Fallback: title similarity with different formats
    candidates = await db.fetch_all(
        """
        WITH book_fmts AS (
            SELECT b.id, b.title, array_agg(DISTINCT bf.format) as formats
            FROM books b JOIN book_files bf ON bf.book_id = b.id
            GROUP BY b.id
        )
        SELECT a.id as id_a, b.id as id_b, a.title as title_a, b.title as title_b,
               a.formats as fmts_a, b.formats as fmts_b,
               similarity(a.title, b.title) as sim
        FROM book_fmts a JOIN book_fmts b ON a.id < b.id
        WHERE similarity(a.title, b.title) > 0.8
          AND a.formats != b.formats
          AND NOT a.formats @> b.formats
        ORDER BY sim DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in candidates]


async def verify_and_stack(id_a: str, id_b: str) -> dict[str, Any]:
    """Verify two books are the same via fingerprint, then stack (merge files into one record)."""
    from brainycat.fingerprints import compute_fingerprint, compare_fingerprints

    # Compute fingerprints if missing
    for bid in (id_a, id_b):
        existing = await db.fetch_one("SELECT 1 FROM book_fingerprints WHERE book_id = $1", UUID(bid))
        if not existing:
            await compute_fingerprint(bid)

    # Compare
    overlap = await compare_fingerprints(id_a, id_b)
    if overlap is None or overlap < 0.3:
        return {"stacked": False, "reason": "content mismatch", "overlap": overlap}

    # Stack: move files from b into a, keep a (better metadata wins)
    a = await db.fetch_one("SELECT quality_score FROM books WHERE id = $1", UUID(id_a))
    b = await db.fetch_one("SELECT quality_score FROM books WHERE id = $1", UUID(id_b))

    keep, merge = (id_a, id_b) if (a["quality_score"] or 0) >= (b["quality_score"] or 0) else (id_b, id_a)

    await db.execute("UPDATE book_files SET book_id = $1 WHERE book_id = $2", UUID(keep), UUID(merge))
    await db.execute("DELETE FROM books WHERE id = $1", UUID(merge))

    return {"stacked": True, "kept": keep, "merged": merge, "overlap": overlap}


async def auto_stack_cycle(limit: int = 10) -> dict[str, Any]:
    """One cycle: find format duplicates and stack them."""
    candidates = await find_format_duplicates(limit=limit)
    stacked = 0
    for c in candidates:
        result = await verify_and_stack(str(c["id_a"]), str(c["id_b"]))
        if result.get("stacked"):
            stacked += 1
    return {"checked": len(candidates), "stacked": stacked}
