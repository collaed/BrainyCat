"""Book DNA / Spotify Wrapped — yearly reading summary card.

Generates a personalized reading summary with stats and insights.
"""

from __future__ import annotations

from typing import Any


async def generate_wrapped(user_id: str, year: int = 2026) -> dict[str, Any]:
    """Generate a 'Spotify Wrapped' style reading summary."""
    from brainycat.db import fetch_all, fetch_one

    # Books finished this year
    finished = await fetch_all(
        """SELECT b.title, b.language, a.name as author
           FROM reading_progress rp
           JOIN books b ON b.id = rp.book_id
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE rp.user_id = $1 AND rp.status = 'finished'
           AND extract(year from rp.finished_at) = $2""",
        user_id,
        year,
    )

    # Reading minutes
    minutes_row = await fetch_one(
        "SELECT COALESCE(sum(minutes), 0) as total FROM reading_log WHERE user_id = $1 AND extract(year from logged_at) = $2",
        user_id,
        year,
    )

    # Most read author
    top_author = await fetch_one(
        """SELECT a.name, count(*) as cnt FROM reading_progress rp
           JOIN books_authors ba ON ba.book_id = rp.book_id
           JOIN authors a ON a.id = ba.author_id
           WHERE rp.user_id = $1 AND rp.status = 'finished'
           AND extract(year from rp.finished_at) = $2
           GROUP BY a.name ORDER BY cnt DESC LIMIT 1""",
        user_id,
        year,
    )

    # Languages
    langs = await fetch_all(
        """SELECT b.language, count(*) as cnt FROM reading_progress rp
           JOIN books b ON b.id = rp.book_id
           WHERE rp.user_id = $1 AND rp.status = 'finished'
           AND extract(year from rp.finished_at) = $2 AND b.language IS NOT NULL
           GROUP BY b.language ORDER BY cnt DESC LIMIT 5""",
        user_id,
        year,
    )

    total_minutes = minutes_row["total"] if minutes_row else 0

    return {
        "year": year,
        "books_finished": len(finished),
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 1),
        "top_author": top_author["name"] if top_author else None,
        "top_author_count": top_author["cnt"] if top_author else 0,
        "languages": [{"lang": r["language"], "count": r["cnt"]} for r in langs],
        "titles": [r["title"] for r in finished[:20]],
    }
