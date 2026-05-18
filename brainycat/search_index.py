"""Full-text search — index book content for search across the entire library."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.content_guard import _sample_epub, _sample_pdf
from brainycat.db import execute, fetch_all, fetch_one


async def index_book(book_id: str) -> dict[str, Any]:
    """Extract text and build a searchable index for a book."""
    import os

    file_row = await fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 ORDER BY created_at LIMIT 1",
        UUID(book_id),
    )
    if not file_row or not os.path.isfile(file_row["file_path"]):
        return {"indexed": False}

    fmt = file_row["format"]
    path = file_row["file_path"]

    # Get more text than content_guard (full extraction for search)
    text = ""
    if fmt == "epub":
        samples = _sample_epub(path)
        text = " ".join(samples)
    elif fmt == "pdf":
        samples = _sample_pdf(path)
        text = " ".join(samples)

    if len(text) < 50:
        return {"indexed": False, "reason": "insufficient text"}

    # Truncate to 50k chars for indexing (PostgreSQL tsvector has limits)
    text = text[:50000]

    await execute(
        """INSERT INTO content_index (book_id, content, search_vector)
           VALUES ($1, $2, to_tsvector('simple', unaccent($2)))
           ON CONFLICT (book_id) DO UPDATE SET content = $2,
           search_vector = to_tsvector('simple', unaccent($2)), updated_at = now()""",
        UUID(book_id), text,
    )
    return {"indexed": True, "chars": len(text)}


async def search_content(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Full-text search across all indexed book content."""
    rows = await fetch_all(
        """SELECT ci.book_id, b.title, b.cover_path,
                  ts_rank(ci.search_vector, plainto_tsquery('simple', unaccent($1))) as rank,
                  ts_headline('simple', ci.content, plainto_tsquery('simple', unaccent($1)),
                    'MaxWords=30, MinWords=10, StartSel=**, StopSel=**') as snippet
           FROM content_index ci
           JOIN books b ON b.id = ci.book_id
           WHERE ci.search_vector @@ plainto_tsquery('simple', unaccent($1))
           ORDER BY rank DESC LIMIT $2""",
        query, limit,
    )
    return [dict(r) for r in rows]


async def index_batch(limit: int = 20) -> dict[str, int]:
    """Index books that haven't been indexed yet."""
    rows = await fetch_all(
        """SELECT b.id FROM books b
           WHERE NOT EXISTS (SELECT 1 FROM content_index ci WHERE ci.book_id = b.id)
           AND EXISTS (SELECT 1 FROM book_files bf WHERE bf.book_id = b.id)
           LIMIT $1""",
        limit,
    )
    indexed = 0
    for r in rows:
        result = await index_book(str(r["id"]))
        if result.get("indexed"):
            indexed += 1
    return {"indexed": indexed, "checked": len(rows)}
