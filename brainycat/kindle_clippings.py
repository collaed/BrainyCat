"""Parse Kindle 'My Clippings.txt' and import highlights/notes."""

from __future__ import annotations

import re
from typing import Any


def parse_clippings(text: str) -> list[dict[str, Any]]:
    """Parse Kindle My Clippings.txt format into structured entries."""
    entries = []
    blocks = text.split("==========")

    for block in blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            continue

        title_author = lines[0]
        meta = lines[1]
        content = "\n".join(lines[2:])

        # Parse title and author
        m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", title_author)
        title = m.group(1).strip() if m else title_author
        author = m.group(2).strip() if m else ""

        # Parse type and location
        clip_type = "highlight"
        if "Note" in meta or "note" in meta:
            clip_type = "note"
        elif "Bookmark" in meta or "bookmark" in meta:
            clip_type = "bookmark"

        loc_match = re.search(r"Location (\d+(?:-\d+)?)", meta)
        location = loc_match.group(1) if loc_match else ""

        page_match = re.search(r"page (\d+)", meta)
        page = int(page_match.group(1)) if page_match else None

        entries.append(
            {
                "title": title,
                "author": author,
                "type": clip_type,
                "text": content,
                "location": location,
                "page": page,
            }
        )

    return entries


async def import_clippings(text: str, user_id: str) -> dict[str, Any]:
    """Import parsed clippings into the database, matching to existing books."""
    from uuid import UUID

    from brainycat.db import execute, fetch_one

    entries = parse_clippings(text)
    imported = 0
    matched_books = set()

    for entry in entries:
        if entry["type"] == "bookmark" or not entry["text"]:
            continue

        # Try to match to existing book by title
        book = await fetch_one(
            "SELECT id FROM books WHERE title ILIKE $1 LIMIT 1",
            f"%{entry['title'][:50]}%",
        )
        book_id = book["id"] if book else None
        if book_id:
            matched_books.add(str(book_id))

        await execute(
            """INSERT INTO clippings (user_id, book_id, text, clip_type, location, page_num, source)
               VALUES ($1, $2, $3, $4, $5, $6, 'kindle')
               ON CONFLICT DO NOTHING""",
            UUID(user_id),
            book_id,
            entry["text"],
            entry["type"],
            entry["location"],
            entry["page"],
        )
        imported += 1

    return {"imported": imported, "total_entries": len(entries), "matched_books": len(matched_books)}
