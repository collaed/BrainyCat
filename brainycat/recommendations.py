"""Book recommendations — 'Because you read X, try Y' using tag similarity."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat import db


async def recommend_similar(book_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find similar books based on shared tags and genre."""
    rows = await db.fetch_all(
        """WITH book_tags AS (
            SELECT tag_id FROM books_tags WHERE book_id = $1
        )
        SELECT b.id, b.title, b.cover_path, b.quality_score,
               count(bt.tag_id) as shared_tags
        FROM books_tags bt
        JOIN books b ON b.id = bt.book_id
        WHERE bt.tag_id IN (SELECT tag_id FROM book_tags)
          AND bt.book_id != $1
        GROUP BY b.id
        ORDER BY shared_tags DESC, b.quality_score DESC
        LIMIT $2""",
        UUID(book_id),
        limit,
    )
    return [dict(r) for r in rows]


async def recommend_for_user(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Recommend books based on user's reading history."""
    rows = await db.fetch_all(
        """WITH user_tags AS (
            SELECT DISTINCT bt.tag_id, count(*) as weight
            FROM reading_progress rp
            JOIN books_tags bt ON bt.book_id = rp.book_id
            WHERE rp.user_id = $1 AND rp.status IN ('finished', 'reading')
            GROUP BY bt.tag_id
        ),
        read_books AS (
            SELECT book_id FROM reading_progress WHERE user_id = $1
        )
        SELECT b.id, b.title, b.cover_path, b.quality_score,
               sum(ut.weight) as relevance
        FROM books_tags bt
        JOIN user_tags ut ON ut.tag_id = bt.tag_id
        JOIN books b ON b.id = bt.book_id
        WHERE bt.book_id NOT IN (SELECT book_id FROM read_books)
        GROUP BY b.id
        ORDER BY relevance DESC, b.quality_score DESC
        LIMIT $2""",
        UUID(user_id),
        limit,
    )
    return [dict(r) for r in rows]


async def recommend_external(title: str, author: str = "") -> dict[str, Any]:
    """Get recommendations from TasteDive (external collaborative filtering)."""
    import httpx

    query = f"book:{title}"
    if author:
        query = f"book:{title} {author}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://tastedive.com/api/similar",
                params={"q": query, "type": "books", "info": 1, "limit": 10},
            )
            if r.status_code == 200:
                data = r.json().get("similar", {}).get("results", [])
                return {
                    "source": "tastedive",
                    "query": title,
                    "results": [
                        {"title": item.get("name", ""), "description": item.get("wTeaser", "")[:200], "type": item.get("type", "")}
                        for item in data
                    ],
                }
    except Exception as e:
        return {"source": "tastedive", "error": str(e)}

    return {"source": "tastedive", "results": []}
