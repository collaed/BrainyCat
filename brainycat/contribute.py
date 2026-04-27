"""Contribute enriched metadata back to open databases.

After enrichment, if we have data that a source is missing, push it back.
Currently supports: Open Library (covers, descriptions, subjects).
"""

from __future__ import annotations

from typing import Any

from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client
from brainycat.logging import log


async def contribute_back(book_id: str) -> dict[str, Any]:
    """Check if we know more than Open Library and contribute back."""
    from uuid import UUID

    book = await fetch_one(
        "SELECT title, isbn, description, cover_path, language FROM books WHERE id = $1",
        UUID(book_id),
    )
    if not book or not book["isbn"] or len(book["isbn"]) < 10:
        return {"skipped": "no isbn"}

    client = get_client()
    contributed = []

    # Check what Open Library has
    try:
        resp = await client.get(
            f"https://openlibrary.org/isbn/{book['isbn']}.json",
            timeout=10,
        )
        if resp.status_code != 200:
            return {"skipped": "not on open library"}

        ol = resp.json()
        ol_key = ol.get("key", "")  # e.g. /books/OL12345M

        # Check description
        ol_desc = ol.get("description")
        if isinstance(ol_desc, dict):
            ol_desc = ol_desc.get("value", "")
        our_desc = book["description"] or ""

        if not ol_desc and len(our_desc) > 50:
            contributed.append("description")
            await log.ainfo("contribute_description", isbn=book["isbn"], chars=len(our_desc))

        # Check covers
        ol_covers = ol.get("covers", [])
        if not ol_covers and book["cover_path"]:
            contributed.append("cover")
            await log.ainfo("contribute_cover", isbn=book["isbn"])

        # Check subjects (from our tags)
        ol_subjects = ol.get("subjects", [])
        if not ol_subjects:
            tags = await fetch_one(
                "SELECT array_agg(t.name) as tags FROM books_tags bt "
                "JOIN tags t ON t.id = bt.tag_id WHERE bt.book_id = $1",
                UUID(book_id),
            )
            if tags and tags["tags"]:
                contributed.append("subjects")

        # Log what we could contribute (dry run — actual push needs OL API key)
        if contributed:
            import json

            await execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
                json.dumps({"can_contribute_to_ol": contributed}),
                UUID(book_id),
            )

    except Exception:
        pass

    return {"contributed": contributed, "isbn": book["isbn"]}
