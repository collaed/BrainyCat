"""Taste-based recommendations using genre/author weights."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def build_profile(user_id: str) -> dict[str, Any]:
    """Build taste profile from finished books."""
    finished = await fetch_all(
        """
        SELECT b.id, b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM reading_progress rp
        JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE rp.user_id = $1 AND rp.is_finished = true
        GROUP BY b.id
    """,
        UUID(user_id),
    )

    genre_w: dict[str, float] = {}
    author_w: dict[str, float] = {}
    for book in finished:
        for tag in book["tags"] or []:
            genre_w[tag] = genre_w.get(tag, 0) + 1
        for auth in book["authors"] or []:
            author_w[auth] = author_w.get(auth, 0) + 2  # 2x weight

    await execute(
        """INSERT INTO taste_profiles (user_id, genre_weights, author_weights, rebuilt_at)
           VALUES ($1, $2, $3, now())
           ON CONFLICT (user_id) DO UPDATE SET genre_weights = $2, author_weights = $3, rebuilt_at = now()""",
        UUID(user_id),
        genre_w,
        author_w,
    )
    return {"genres": genre_w, "authors": author_w, "books_analyzed": len(finished)}


async def get_recommendations(user_id: str, category: str = "all") -> list[dict[str, Any]]:
    """Get recommendations for a user."""
    profile = await fetch_one("SELECT * FROM taste_profiles WHERE user_id = $1", UUID(user_id))
    if not profile:
        return []

    if category == "authors_you_love":
        author_w = profile["author_weights"] or {}
        top_authors = sorted(author_w, key=author_w.get, reverse=True)[:5]
        if not top_authors:
            return []
        rows = await fetch_all(
            """
            SELECT DISTINCT b.id, b.title, a.name as author FROM books b
            JOIN books_authors ba ON ba.book_id = b.id JOIN authors a ON a.id = ba.author_id
            LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
            WHERE a.name = ANY($2) AND rp.id IS NULL LIMIT 20
        """,
            UUID(user_id),
            top_authors,
        )
        return [{"id": str(r["id"]), "title": r["title"], "author": r["author"], "reason": "author_match"} for r in rows]

    if category == "complete_series":
        rows = await fetch_all(
            """
            SELECT s.name, array_agg(b.series_index ORDER BY b.series_index) as owned,
                   max(b.series_index) as max_idx
            FROM reading_progress rp
            JOIN books b ON b.id = rp.book_id
            JOIN books_series bs ON bs.book_id = b.id JOIN series s ON s.id = bs.series_id
            WHERE rp.user_id = $1
            GROUP BY s.name
        """,
            UUID(user_id),
        )
        return [{"series": r["name"], "owned": r["owned"], "next": int(max(r["owned"] or [0])) + 1} for r in rows]

    # Default: unread books sorted by quality
    rows = await fetch_all(
        """
        SELECT b.id, b.title, b.quality_score FROM books b
        LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
        WHERE rp.id IS NULL ORDER BY b.quality_score DESC LIMIT 20
    """,
        UUID(user_id),
    )
    return [{"id": str(r["id"]), "title": r["title"], "quality_score": r["quality_score"]} for r in rows]
