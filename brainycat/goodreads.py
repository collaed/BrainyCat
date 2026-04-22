"""Goodreads full integration — import shelves, ratings, reading dates from CSV."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one


async def import_goodreads_csv(csv_content: str, user_id: str) -> dict[str, Any]:
    """Import a Goodreads library export CSV.

    Expected columns: Book Id, Title, Author, Author l-f, Additional Authors,
    ISBN, ISBN13, My Rating, Average Rating, Publisher, Binding, Number of Pages,
    Year Published, Original Publication Year, Date Read, Date Added,
    Bookshelves, Bookshelves with positions, Exclusive Shelf, My Review, Spoiler,
    Private Notes, Read Count, Owned Copies
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    imported = 0
    matched = 0
    skipped = 0
    ratings_set = 0
    shelves_created: set[str] = set()

    for row in reader:
        title = (row.get("Title") or "").strip()
        author = (row.get("Author") or "").strip()
        isbn13 = _clean_isbn(row.get("ISBN13", ""))
        isbn10 = _clean_isbn(row.get("ISBN", ""))
        isbn = isbn13 or isbn10
        my_rating = int(row.get("My Rating") or 0)
        avg_rating = float(row.get("Average Rating") or 0)
        date_read = _parse_date(row.get("Date Read", ""))
        _parse_date(row.get("Date Added", ""))
        shelves = [s.strip() for s in (row.get("Bookshelves") or "").split(",") if s.strip()]
        exclusive = (row.get("Exclusive Shelf") or "").strip()
        pages = int(row.get("Number of Pages") or 0) if (row.get("Number of Pages") or "").strip() else 0
        (row.get("Publisher") or "").strip()

        # Try to match existing book
        book_id = None
        if isbn:
            existing = await fetch_one("SELECT id FROM books WHERE isbn = $1", isbn)
            if existing:
                book_id = existing["id"]
                matched += 1
        if not book_id and title:
            existing = await fetch_one("SELECT id FROM books WHERE lower(title) = lower($1)", title)
            if existing:
                book_id = existing["id"]
                matched += 1

        if not book_id:
            # Create new book
            book_id = uuid4()
            await execute(
                "INSERT INTO books (id, title, isbn, description, rating, page_count) VALUES ($1,$2,$3,$4,$5,$6)",
                book_id,
                title,
                isbn,
                "",
                avg_rating,
                pages or None,
            )
            # Author
            if author:
                author_row = await fetch_one("SELECT id FROM authors WHERE name = $1", author)
                if not author_row:
                    aid = uuid4()
                    await execute("INSERT INTO authors (id, name) VALUES ($1,$2)", aid, author)
                else:
                    aid = author_row["id"]
                await execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", book_id, aid)
            imported += 1

        # Set user rating
        if my_rating > 0:
            await execute("UPDATE books SET rating = $1 WHERE id = $2 AND (rating IS NULL OR rating = 0)", float(my_rating) * 2, book_id)
            ratings_set += 1

        # Set page count if missing
        if pages > 0:
            await execute("UPDATE books SET page_count = $1 WHERE id = $2 AND page_count IS NULL", pages, book_id)

        # Create reading progress if date_read
        if date_read and exclusive == "read":
            await execute(
                """
                INSERT INTO reading_progress (id, user_id, book_id, percentage, is_finished, updated_at)
                VALUES ($1, $2, $3, 1.0, true, $4)
                ON CONFLICT (user_id, book_id) DO UPDATE SET is_finished = true, percentage = 1.0
            """,
                uuid4(),
                UUID(user_id),
                book_id,
                date_read,
            )

        # Shelves → tags
        for shelf in shelves:
            shelf_clean = shelf.replace("-", " ").strip()
            if shelf_clean and shelf_clean not in ("to-read", "currently-reading", "read"):
                await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", shelf_clean)
                tag_row = await fetch_one("SELECT id FROM tags WHERE name = $1", shelf_clean)
                if tag_row:
                    await execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", book_id, tag_row["id"])
                    shelves_created.add(shelf_clean)

    return {
        "imported": imported,
        "matched": matched,
        "ratings_set": ratings_set,
        "shelves_created": list(shelves_created),
        "total_rows": imported + matched + skipped,
    }


def _clean_isbn(raw: str) -> str | None:
    """Clean ISBN from Goodreads format (="0123456789")."""
    cleaned = re.sub(r'[=""\s-]', "", raw)
    if len(cleaned) in (10, 13) and cleaned.replace("X", "0").isdigit():
        return cleaned
    return None


def _parse_date(s: str) -> datetime | None:
    """Parse Goodreads date formats."""
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None
