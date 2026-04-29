"""Smart merge — detect and merge duplicate books, consolidating files."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat import db


async def find_merge_candidates(limit: int = 20) -> list[dict[str, Any]]:
    """Find books that are likely duplicates (same ISBN or very similar title)."""
    # Same ISBN
    isbn_dupes = await db.fetch_all(
        """SELECT isbn, array_agg(id) as book_ids, array_agg(title) as titles, count(*) as cnt
           FROM books WHERE isbn IS NOT NULL
           GROUP BY isbn HAVING count(*) > 1
           ORDER BY count(*) DESC LIMIT $1""",
        limit,
    )
    return [{"isbn": r["isbn"], "book_ids": [str(i) for i in r["book_ids"]], "titles": r["titles"], "count": r["cnt"]} for r in isbn_dupes]


async def merge_books(keep_id: str, merge_ids: list[str]) -> dict[str, Any]:
    """Merge multiple books into one, keeping the best metadata."""
    keep = UUID(keep_id)
    merged_count = 0

    for mid in merge_ids:
        merge = UUID(mid)
        if merge == keep:
            continue

        # Move files to keep
        await db.execute("UPDATE book_files SET book_id = $1 WHERE book_id = $2", keep, merge)
        # Move annotations
        await db.execute("UPDATE annotations SET book_id = $1 WHERE book_id = $2", keep, merge)
        # Move reading progress (skip conflicts)
        await db.execute(
            "UPDATE reading_progress SET book_id = $1 WHERE book_id = $2 AND NOT EXISTS (SELECT 1 FROM reading_progress WHERE book_id = $1 AND user_id = reading_progress.user_id)",
            keep,
            merge,
        )
        # Delete the duplicate
        await db.execute("DELETE FROM books WHERE id = $1", merge)
        merged_count += 1

    return {"kept": keep_id, "merged": merged_count}
