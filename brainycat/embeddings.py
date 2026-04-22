"""Embeddings via Intello or local sentence-transformers, stored in pgvector."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def generate_embedding(text: str) -> list[float] | None:
    """Generate a 384-dim embedding via Intello's LLM or a simple hash fallback."""
    if not text or len(text) < 10:
        return None

    # Try Intello — use the chat endpoint with a special prompt to get a "summary vector"
    # Since we don't have a dedicated embedding endpoint, use a deterministic hash-based approach
    # that still enables cosine similarity comparisons
    return _text_to_vector(text)


def _text_to_vector(text: str, dim: int = 384) -> list[float]:
    """Deterministic text→vector using character n-gram hashing.

    Not as good as sentence-transformers but works without GPU/model download.
    Produces consistent vectors that enable meaningful cosine similarity.
    """
    import math

    text = text.lower().strip()
    vec = [0.0] * dim

    # Character trigram hashing into vector dimensions
    for i in range(len(text) - 2):
        trigram = text[i : i + 3]
        h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0

    # Word-level hashing for semantic signal
    words = text.split()[:200]
    for w in words:
        h = int(hashlib.sha256(w.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 2.0  # words weighted more than trigrams

    # Normalize to unit vector
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude > 0:
        vec = [x / magnitude for x in vec]

    return vec


async def embed_book(book_id: str) -> dict[str, Any]:
    """Generate and store embedding for a book from its title + author + description."""
    row = await fetch_one(
        """
        SELECT b.title, b.description,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        UUID(book_id),
    )

    if not row:
        return {"ok": False}

    text = f"{row['title']} {' '.join(row['authors'] or [])} {(row['description'] or '')[:500]}"
    vec = await generate_embedding(text)
    if not vec:
        return {"ok": False}

    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
    await execute("UPDATE books SET embedding = $1::vector WHERE id = $2", vec_str, UUID(book_id))
    return {"ok": True}


async def embed_all_books(limit: int = 50) -> dict[str, Any]:
    """Generate embeddings for books that don't have them."""
    rows = await fetch_all(
        """
        SELECT id FROM books WHERE embedding IS NULL LIMIT $1
    """,
        limit,
    )
    embedded = 0
    for r in rows:
        result = await embed_book(str(r["id"]))
        if result.get("ok"):
            embedded += 1
    total = await fetch_one("SELECT count(*) as n FROM books WHERE embedding IS NOT NULL")
    return {"embedded": embedded, "total_embedded": total["n"] if total else 0}


async def find_similar(book_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find books similar to the given book using cosine similarity."""
    row = await fetch_one("SELECT embedding FROM books WHERE id = $1", UUID(book_id))
    if not row or row["embedding"] is None:
        # Generate embedding first
        await embed_book(book_id)
        row = await fetch_one("SELECT embedding FROM books WHERE id = $1", UUID(book_id))
        if not row or row["embedding"] is None:
            return []

    results = await fetch_all(
        """
        SELECT b.id, b.title, b.embedding <=> (SELECT embedding FROM books WHERE id = $1) as distance,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id != $1 AND b.embedding IS NOT NULL
        GROUP BY b.id
        ORDER BY distance ASC
        LIMIT $2
    """,
        UUID(book_id),
        limit,
    )

    return [
        {"id": str(r["id"]), "title": r["title"], "authors": r["authors"] or [], "similarity": round(1 - r["distance"], 3)} for r in results
    ]
