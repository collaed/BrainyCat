"""Reviews aggregation from multiple sources."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx

from brainycat.db import execute, fetch_all, fetch_one


async def get_reviews(book_id: str) -> dict[str, Any]:
    """Get aggregated reviews, using cache if fresh."""
    cached = await fetch_all("SELECT * FROM book_reviews_cache WHERE book_id = $1", UUID(book_id))
    if cached and all((c["fetched_at"]).timestamp() > (asyncio.get_event_loop().time() - 86400) for c in cached):
        return _aggregate(cached)

    book = await fetch_one("SELECT * FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return {"error": "not found"}

    # Fetch from sources in parallel
    results = await asyncio.gather(
        _fetch_google_books(book["title"], book["isbn"]),
        _fetch_open_library(book["isbn"]),
        return_exceptions=True,
    )

    for r in results:
        if isinstance(r, dict) and r.get("source"):
            await execute(
                """INSERT INTO book_reviews_cache (book_id, source, rating, review_count, data, fetched_at)
                   VALUES ($1,$2,$3,$4,$5,now())
                   ON CONFLICT (book_id, source) DO UPDATE SET rating=$3, review_count=$4, data=$5, fetched_at=now()""",
                UUID(book_id),
                r["source"],
                r.get("rating"),
                r.get("review_count", 0),
                r,
            )

    all_cached = await fetch_all("SELECT * FROM book_reviews_cache WHERE book_id = $1", UUID(book_id))
    return _aggregate(all_cached)


async def _fetch_google_books(title: str | None, isbn: str | None) -> dict[str, Any]:
    from brainycat.sources.google_books import search

    r = await search(title=title, isbn=isbn)
    if r and r.get("rating"):
        return {"source": "google_books", "rating": r["rating"], "review_count": r.get("rating_count", 0)}
    return {}


async def _fetch_open_library(isbn: str | None) -> dict[str, Any]:
    if not isbn:
        return {}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"https://openlibrary.org/isbn/{isbn}.json")
        if resp.status_code != 200:
            return {}
        data = resp.json()
        works_key = next(iter(data.get("works", [])), {}).get("key")
        if not works_key:
            return {}
        resp2 = await client.get(f"https://openlibrary.org{works_key}/ratings.json")
        if resp2.status_code == 200:
            rd = resp2.json()
            return {
                "source": "open_library",
                "rating": rd.get("summary", {}).get("average"),
                "review_count": rd.get("summary", {}).get("count", 0),
            }
    return {}


def _aggregate(rows: list[Any]) -> dict[str, Any]:
    sources = []
    total_rating = 0.0
    total_weight = 0
    for r in rows:
        if r["rating"]:
            sources.append({"source": r["source"], "rating": float(r["rating"]), "count": r["review_count"]})
            weight = max(1, r["review_count"])
            total_rating += float(r["rating"]) * weight
            total_weight += weight
    avg = total_rating / total_weight if total_weight else None
    return {"average_rating": round(avg, 2) if avg else None, "sources": sources}
