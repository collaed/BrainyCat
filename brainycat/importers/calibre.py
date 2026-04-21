"""Importers — Calibre, Goodreads, Audiobookshelf."""

from __future__ import annotations

import csv
import io
import os
import sqlite3
from typing import Any
from uuid import uuid4

from brainycat.db import execute, fetch_one


async def import_calibre(metadata_db_path: str, books_dir: str) -> dict[str, Any]:
    """Import from Calibre metadata.db."""
    conn = sqlite3.connect(metadata_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM books ORDER BY id").fetchall()
    imported = 0
    for r in rows:
        book_id = uuid4()
        title = r["title"]
        # Check duplicate
        dup = await fetch_one("SELECT id FROM books WHERE title = $1", title)
        if dup:
            continue
        await execute(
            "INSERT INTO books (id, title, sort_title, isbn, pubdate) VALUES ($1,$2,$3,$4,$5)",
            book_id,
            title,
            r["sort"],
            None,
            None,
        )
        # Authors
        authors = conn.execute(
            "SELECT a.name FROM books_authors_link bal JOIN authors a ON a.id = bal.author WHERE bal.book = ?",
            (r["id"],),
        ).fetchall()
        for a in authors:
            await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", a["name"])
            ar = await fetch_one("SELECT id FROM authors WHERE name = $1", a["name"])
            if ar:
                await execute(
                    "INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    book_id,
                    ar["id"],
                )
        # Files
        book_path = os.path.join(books_dir, r["path"])
        if os.path.isdir(book_path):
            for f in os.listdir(book_path):
                ext = os.path.splitext(f)[1].lower()
                if ext in {".epub", ".pdf", ".mobi", ".azw3"}:
                    fp = os.path.join(book_path, f)
                    await execute(
                        "INSERT INTO book_files (book_id, format, file_path, file_name, file_size) VALUES ($1,$2,$3,$4,$5)",
                        book_id,
                        ext.lstrip("."),
                        fp,
                        f,
                        os.path.getsize(fp),
                    )
        imported += 1
    conn.close()
    return {"imported": imported}


async def import_goodreads(csv_content: str) -> dict[str, Any]:
    """Import from Goodreads CSV export."""
    reader = csv.DictReader(io.StringIO(csv_content))
    imported = 0
    for row in reader:
        title = row.get("Title", "").strip()
        if not title:
            continue
        dup = await fetch_one("SELECT id FROM books WHERE title = $1", title)
        if dup:
            continue
        book_id = uuid4()
        await execute(
            "INSERT INTO books (id, title, isbn) VALUES ($1,$2,$3)",
            book_id,
            title,
            row.get("ISBN13", "").strip('"= ') or None,
        )
        author = row.get("Author", "").strip()
        if author:
            await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", author)
            ar = await fetch_one("SELECT id FROM authors WHERE name = $1", author)
            if ar:
                await execute(
                    "INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    book_id,
                    ar["id"],
                )
        imported += 1
    return {"imported": imported}


async def import_audiobookshelf(db_path: str = "/opt/audiobookshelf/config/absdatabase.sqlite") -> dict[str, Any]:
    """Import from audiobookshelf SQLite database."""
    if not os.path.isfile(db_path):
        return {"error": f"Database not found: {db_path}"}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # ABS uses libraryItems table
    try:
        rows = conn.execute("SELECT * FROM libraryItems").fetchall()
    except sqlite3.OperationalError:
        rows = []
    imported = 0
    for r in rows:
        import json

        media = json.loads(r["media"]) if "media" in r else {}
        meta = media.get("metadata", {})
        title = meta.get("title", "Unknown")
        dup = await fetch_one("SELECT id FROM books WHERE title = $1", title)
        if dup:
            continue
        book_id = uuid4()
        await execute(
            "INSERT INTO books (id, title, description) VALUES ($1,$2,$3)",
            book_id,
            title,
            meta.get("description"),
        )
        author = meta.get("authorName")
        if author:
            await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", author)
            ar = await fetch_one("SELECT id FROM authors WHERE name = $1", author)
            if ar:
                await execute(
                    "INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    book_id,
                    ar["id"],
                )
        imported += 1
    conn.close()
    return {"imported": imported}
