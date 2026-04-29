"""Import reading history from Goodreads or StoryGraph CSV export."""

from __future__ import annotations

import csv
import io
from typing import Any

from brainycat import db


async def import_goodreads_csv(csv_text: str, user_id: str) -> dict[str, Any]:
    """Parse Goodreads CSV and import books + reading status."""
    from uuid import UUID

    reader = csv.DictReader(io.StringIO(csv_text))
    imported = 0
    matched = 0

    for row in reader:
        title = row.get("Title", "").strip()
        author = row.get("Author", "").strip()
        isbn = (row.get("ISBN13") or row.get("ISBN", "")).strip().strip('="')
        rating = row.get("My Rating", "0")
        shelf = row.get("Exclusive Shelf", row.get("Bookshelves", ""))
        date_read = row.get("Date Read", "")

        if not title:
            continue

        # Map Goodreads shelf to our status
        status_map = {"read": "finished", "currently-reading": "reading", "to-read": "want_to_read"}
        status = status_map.get(shelf, "library")

        # Try to match existing book
        book = await db.fetch_one("SELECT id FROM books WHERE title ILIKE $1 LIMIT 1", f"%{title[:50]}%")

        if not book and isbn and len(isbn) >= 10:
            book = await db.fetch_one("SELECT id FROM books WHERE isbn = $1", isbn)

        if book:
            matched += 1
            # Update reading status
            await db.execute(
                """INSERT INTO reading_progress (user_id, book_id, status, percentage)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (user_id, book_id) DO UPDATE SET status = $3""",
                UUID(user_id),
                book["id"],
                status,
                100.0 if status == "finished" else 0.0,
            )
        else:
            # Create book entry
            new_book = await db.fetch_one(
                "INSERT INTO books (title, isbn, quality_score) VALUES ($1, $2, 20) RETURNING id",
                title,
                isbn if isbn else None,
            )
            if new_book:
                if author:
                    a = await db.fetch_one(
                        "INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = $1 RETURNING id",
                        author,
                    )
                    if a:
                        await db.execute(
                            "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", new_book["id"], a["id"]
                        )
                await db.execute(
                    """INSERT INTO reading_progress (user_id, book_id, status, percentage)
                       VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""",
                    UUID(user_id),
                    new_book["id"],
                    status,
                    100.0 if status == "finished" else 0.0,
                )
                imported += 1

    return {"imported": imported, "matched": matched, "total": imported + matched}
