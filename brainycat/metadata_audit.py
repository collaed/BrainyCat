"""Metadata audit trail + drift detection.

Tracks every metadata change with source attribution.
Detects when current metadata has drifted too far from the original file identity.
Flags suspicious changes for user review.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from brainycat import db


async def record_change(book_id: str, field: str, old_value: Any, new_value: Any, source: str) -> None:
    """Record a metadata change in the audit trail."""
    if str(old_value) == str(new_value):
        return
    await db.execute(
        "INSERT INTO metadata_history (book_id, field, old_value, new_value, source) VALUES ($1, $2, $3, $4, $5)",
        UUID(book_id),
        field,
        str(old_value)[:500] if old_value else None,
        str(new_value)[:500] if new_value else None,
        source,
    )


async def get_history(book_id: str) -> list[dict[str, Any]]:
    """Get full change history for a book."""
    rows = await db.fetch_all(
        "SELECT field, old_value, new_value, source, created_at FROM metadata_history WHERE book_id = $1 ORDER BY created_at",
        UUID(book_id),
    )
    return [dict(r) for r in rows]


async def check_drift(book_id: str) -> dict[str, Any]:
    """Check if current metadata has drifted too far from original identity.

    Compares current title against original_filename/original_title.
    If no common words remain, flags for user review.
    """
    book = await db.fetch_one(
        "SELECT b.title, b.isbn, bo.original_title, bo.original_filename FROM books b LEFT JOIN book_originals bo ON bo.book_id = b.id WHERE b.id = $1",
        UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    current_title = (book["title"] or "").lower()
    original_title = (book["original_title"] or "").lower()
    original_filename = (book["original_filename"] or "").lower()

    # Extract meaningful words (3+ chars, no common stopwords)
    stopwords = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "les", "des", "une", "par"}

    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"\b\w{3,}\b", text) if w not in stopwords}

    current_words = words(current_title)
    original_words = words(original_title) | words(original_filename)

    if not current_words or not original_words:
        return {"drift": False, "reason": "insufficient data"}

    common = current_words & original_words
    similarity = len(common) / max(len(current_words), 1)

    # Also check string similarity
    str_sim = SequenceMatcher(None, current_title, original_title).ratio() if original_title else 0

    drifted = similarity < 0.2 and str_sim < 0.3

    return {
        "drift": drifted,
        "current_title": book["title"],
        "original_title": book["original_title"],
        "original_filename": book["original_filename"],
        "common_words": list(common)[:10],
        "word_overlap": round(similarity, 2),
        "string_similarity": round(str_sim, 2),
    }


async def find_drifted_books(limit: int = 20) -> list[dict[str, Any]]:
    """Find all books where metadata has drifted significantly from original."""
    books = await db.fetch_all(
        """SELECT b.id, b.title, bo.original_title, bo.original_filename
           FROM books b JOIN book_originals bo ON bo.book_id = b.id
           WHERE bo.original_title IS NOT NULL AND b.title != bo.original_title
           LIMIT $1""",
        limit * 3,  # Fetch more, filter in Python
    )

    drifted = []
    for book in books:
        result = await check_drift(str(book["id"]))
        if result.get("drift"):
            drifted.append({"book_id": str(book["id"]), **result})
            if len(drifted) >= limit:
                break

    return drifted


async def rollback_field(book_id: str, field: str) -> dict[str, Any]:
    """Rollback a field to its previous value (from history)."""
    # Get the oldest recorded value for this field
    row = await db.fetch_one(
        "SELECT old_value FROM metadata_history WHERE book_id = $1 AND field = $2 ORDER BY created_at ASC LIMIT 1",
        UUID(book_id),
        field,
    )
    if not row or not row["old_value"]:
        return {"error": "no history for this field"}

    original = row["old_value"]
    await db.execute(f"UPDATE books SET {field} = $1 WHERE id = $2", original, UUID(book_id))
    await record_change(book_id, field, None, original, "user_rollback")
    return {"rolled_back": field, "to": original}
