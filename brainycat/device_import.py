"""Kindle annotation import — parse My Clippings.txt and sidecar files."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one


async def import_kindle_clippings(content: str, user_id: str) -> dict[str, Any]:
    """Parse Kindle's My Clippings.txt and import annotations.

    Format:
    Book Title (Author Name)
    - Your Highlight on page X | Location Y-Z | Added on Day, Month DD, YYYY HH:MM:SS AM/PM

    Highlight text here
    ==========
    """
    entries = content.split("==========")
    imported = 0
    matched = 0
    skipped = 0

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        lines = entry.split("\n")
        if len(lines) < 3:
            skipped += 1
            continue

        # Line 1: "Book Title (Author Name)" or just "Book Title"
        title_line = lines[0].strip()
        author_match = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", title_line)
        if author_match:
            title = author_match.group(1).strip()
            author_match.group(2).strip()
        else:
            title = title_line

        # Line 2: metadata (highlight/note, page, location, date)
        meta_line = lines[1].strip() if len(lines) > 1 else ""
        is_note = "Note" in meta_line
        page_match = re.search(r"page (\d+)", meta_line)
        page = int(page_match.group(1)) if page_match else None
        loc_match = re.search(r"Location (\d+)", meta_line)
        location = int(loc_match.group(1)) if loc_match else None

        # Lines 3+: the actual highlight/note text
        text = "\n".join(lines[2:]).strip()
        if not text:
            skipped += 1
            continue

        # Match to library book
        book_row = await fetch_one("SELECT id FROM books WHERE lower(title) = lower($1)", title)
        if not book_row:
            # Try partial match
            book_row = await fetch_one("SELECT id FROM books WHERE lower(title) LIKE '%' || lower($1) || '%'", title[:50])

        if book_row:
            matched += 1
            await execute(
                """
                INSERT INTO annotations (id, user_id, book_id, content, annotation_type, position, is_shared)
                VALUES ($1, $2, $3, $4, $5, $6, false)
            """,
                uuid4(),
                UUID(user_id),
                book_row["id"],
                text,
                "note" if is_note else "highlight",
                str(location or page or 0),
            )
            imported += 1
        else:
            skipped += 1

    return {"imported": imported, "matched": matched, "skipped": skipped, "total": len(entries)}


async def import_kobo_annotations(db_path: str, user_id: str) -> dict[str, Any]:
    """Import annotations from Kobo's KoboReader.sqlite."""
    import sqlite3

    if not db_path.endswith("KoboReader.sqlite"):
        return {"error": "not a Kobo database"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    imported = 0
    matched = 0

    for row in conn.execute("""
        SELECT bm.Text, bm.Annotation, bm.ContentID, c.Title, c.Attribution
        FROM Bookmark bm
        LEFT JOIN content c ON c.ContentID = bm.VolumeID
        WHERE bm.Text IS NOT NULL AND bm.Text != ''
    """):
        title = row["Title"] or ""
        text = row["Text"] or ""
        note = row["Annotation"] or ""

        book_row = await fetch_one("SELECT id FROM books WHERE lower(title) = lower($1)", title)
        if book_row:
            matched += 1
            content = f"{text}\n---\n{note}" if note else text
            await execute(
                """
                INSERT INTO annotations (id, user_id, book_id, content, annotation_type, is_shared)
                VALUES ($1, $2, $3, $4, 'highlight', false)
            """,
                uuid4(),
                UUID(user_id),
                book_row["id"],
                content,
            )
            imported += 1

    conn.close()
    return {"imported": imported, "matched": matched}
