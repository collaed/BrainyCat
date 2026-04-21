"""Reading statistics and book notes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def get_stats(user_id: str) -> dict[str, Any]:
    """Compute reading statistics for a user."""
    finished = await fetch_all(
        """
        SELECT rp.updated_at, b.title, array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as genres
        FROM reading_progress rp JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE rp.user_id = $1 AND rp.is_finished = true GROUP BY rp.id, b.title ORDER BY rp.updated_at
    """,
        UUID(user_id),
    )

    genre_counts: dict[str, int] = {}
    monthly: dict[str, int] = {}
    for r in finished:
        for g in r["genres"] or []:
            genre_counts[g] = genre_counts.get(g, 0) + 1
        if r["updated_at"]:
            key = r["updated_at"].strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + 1

    # Streak calculation
    in_progress = await fetch_all(
        "SELECT DISTINCT DATE(updated_at) as d FROM reading_progress WHERE user_id = $1 ORDER BY d DESC",
        UUID(user_id),
    )
    streak = 0
    from datetime import date, timedelta

    today = date.today()
    for r in in_progress:
        expected = today - timedelta(days=streak)
        if r["d"] == expected:
            streak += 1
        else:
            break

    return {
        "total_finished": len(finished),
        "books_per_month": monthly,
        "genre_distribution": genre_counts,
        "current_streak_days": streak,
    }


async def get_note(user_id: str, book_id: str) -> dict[str, Any] | None:
    row = await fetch_one("SELECT * FROM book_notes WHERE user_id = $1 AND book_id = $2", UUID(user_id), UUID(book_id))
    return dict(row) if row else None


async def save_note(user_id: str, book_id: str, content: str) -> dict[str, Any]:
    await execute(
        """INSERT INTO book_notes (user_id, book_id, content, updated_at)
           VALUES ($1,$2,$3,now())
           ON CONFLICT (user_id, book_id) DO UPDATE SET content = $3, updated_at = now()""",
        UUID(user_id),
        UUID(book_id),
        content,
    )
    return {"ok": True}


async def export_notes(user_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT bn.content, bn.updated_at, b.title FROM book_notes bn
        JOIN books b ON b.id = bn.book_id WHERE bn.user_id = $1 ORDER BY bn.updated_at DESC
    """,
        UUID(user_id),
    )
    return [{"title": r["title"], "content": r["content"], "updated_at": r["updated_at"].isoformat()} for r in rows]
