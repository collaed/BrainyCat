"""Manual identity override — "this book is misidentified, here's the truth" reset.

Wipes everything enrichment derived from the wrong identity (tags, extra_metadata, enrichment_log)
and sets the book to 'protected': automated enrichment may still fill in genuinely missing data
(description, cover, tags) but must not overwrite title/author/isbn again until the user reviews
and explicitly 'locks' the book, or reverts it back to 'auto'.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one
from brainycat.isbn import _clean_isbn
from brainycat.metadata_audit import record_change


async def apply_override(
    book_id: str,
    title: str | None = None,
    author: str | None = None,
    isbn: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    book = await fetch_one("SELECT title, isbn, description FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return {"error": "not found"}

    clean_isbn = None
    if isbn:
        clean_isbn = _clean_isbn(isbn)
        if not clean_isbn:
            return {"error": f"'{isbn}' doesn't checksum-validate as an ISBN-10/13"}

    # Record every change for the audit trail before touching anything.
    if title and title != book["title"]:
        await record_change(book_id, "title", book["title"], title, "manual_override")
    if clean_isbn and clean_isbn != book["isbn"]:
        await record_change(book_id, "isbn", book["isbn"], clean_isbn, "manual_override")
    if description and description != book["description"]:
        await record_change(book_id, "description", book["description"], description, "manual_override")

    sets, vals = [], []
    idx = 1
    for field, value in (("title", title), ("isbn", clean_isbn), ("description", description)):
        if value:
            sets.append(f"{field} = ${idx}")
            vals.append(value)
            idx += 1
    sets.append(f"identity_status = ${idx}")
    vals.append("protected")
    idx += 1
    sets.append("quality_score = 0")
    sets.append("extra_metadata = '{}'::jsonb")  # wipe enrichment-derived bisac codes, OL work id, etc.
    vals.append(UUID(book_id))
    await execute(f"UPDATE books SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)

    # Wipe tags/authors derived from the wrong identity — restart from scratch means restart.
    await execute("DELETE FROM books_tags WHERE book_id = $1", UUID(book_id))
    await execute("DELETE FROM books_authors WHERE book_id = $1", UUID(book_id))
    if author:
        await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", author)
        author_row = await fetch_one("SELECT id FROM authors WHERE name = $1", author)
        if author_row:
            await execute(
                "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                UUID(book_id),
                author_row["id"],
            )

    # Clear enrichment attempt history so the next background pass retries fresh from the new identity.
    await execute("DELETE FROM enrichment_log WHERE book_id = $1", UUID(book_id))

    return {"ok": True, "book_id": book_id, "identity_status": "protected"}


async def lock_book(book_id: str) -> dict[str, Any]:
    """User declares the book's metadata complete and correct — freeze it against any automated write."""
    await execute("UPDATE books SET identity_status = 'locked', updated_at = now() WHERE id = $1", UUID(book_id))
    return {"ok": True, "identity_status": "locked"}


async def unlock_book(book_id: str) -> dict[str, Any]:
    """Escape hatch — return a protected/locked book to normal automated enrichment."""
    await execute("UPDATE books SET identity_status = 'auto', updated_at = now() WHERE id = $1", UUID(book_id))
    return {"ok": True, "identity_status": "auto"}
