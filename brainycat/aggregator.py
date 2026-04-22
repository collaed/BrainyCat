"""Multi-source metadata aggregation — like CineCross's TMDB+OMDB+TVDB+Trakt.

Aggregates: Google Books + Open Library + Amazon + Gutendex + Library of Congress
into a unified view per book, showing what each source knows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import fetch_all, fetch_one


async def aggregate_metadata(book_id: str) -> dict[str, Any]:
    """Get metadata from all sources for a single book, side by side."""
    book = await fetch_one(
        """
        SELECT b.title, b.isbn,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    # Get enrichment log — what each source returned
    logs = await fetch_all(
        "SELECT method, details, created_at FROM enrichment_log WHERE book_id = $1 ORDER BY created_at DESC",
        UUID(book_id),
    )

    sources: dict[str, Any] = {}
    for log in logs:
        src = log["method"]
        if src not in sources:
            sources[src] = log["details"] if isinstance(log["details"], dict) else {"raw": log["details"]}

    # Build comparison matrix
    fields = ["title", "authors", "description", "isbn", "publisher", "published_date", "page_count", "rating", "cover_url", "series"]
    matrix: dict[str, dict[str, Any]] = {}
    for field in fields:
        matrix[field] = {}
        for src, data in sources.items():
            if isinstance(data, dict) and field in data:
                matrix[field][src] = data[field]

    return {
        "book": {"title": book["title"], "isbn": book["isbn"], "authors": book["authors"]},
        "sources": list(sources.keys()),
        "source_data": sources,
        "comparison": matrix,
        "coverage": {src: sum(1 for f in fields if isinstance(data, dict) and f in data) for src, data in sources.items()},
    }


async def library_source_coverage() -> dict[str, Any]:
    """Dashboard: how well each source covers the library."""
    total = await fetch_one("SELECT count(*) as n FROM books")
    total_n = total["n"] if total else 0

    source_stats = await fetch_all("""
        SELECT method as source, count(DISTINCT book_id) as books_covered,
               count(*) as total_lookups
        FROM enrichment_log
        WHERE success = true
        GROUP BY method ORDER BY books_covered DESC
    """)

    return {
        "total_books": total_n,
        "sources": [
            {
                "name": r["source"],
                "books_covered": r["books_covered"],
                "coverage_pct": round(r["books_covered"] / max(total_n, 1) * 100, 1),
                "total_lookups": r["total_lookups"],
            }
            for r in source_stats
        ],
    }
