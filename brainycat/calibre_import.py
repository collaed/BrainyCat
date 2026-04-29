"""Import books from an existing Calibre library (reads metadata.db SQLite)."""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from brainycat import db


async def import_calibre_library(calibre_path: str, limit: int = 100) -> dict[str, Any]:
    """Import books from a Calibre library folder."""
    db_path = os.path.join(calibre_path, "metadata.db")
    if not os.path.isfile(db_path):
        return {"error": f"metadata.db not found at {calibre_path}"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get books with their paths
    cur.execute(
        """
        SELECT b.id, b.title, b.sort, b.path, b.isbn, b.pubdate,
               (SELECT group_concat(a.name, ', ') FROM books_authors_link bal
                JOIN authors a ON a.id = bal.author WHERE bal.book = b.id) as authors,
               (SELECT group_concat(t.name, ', ') FROM books_tags_link btl
                JOIN tags t ON t.id = btl.tag WHERE btl.book = b.id) as tags,
               (SELECT group_concat(d.format || ':' || d.name, '|') FROM data d WHERE d.book = b.id) as formats,
               (SELECT text FROM comments WHERE book = b.id) as description,
               (SELECT group_concat(p.name, ', ') FROM books_publishers_link bpl
                JOIN publishers p ON p.id = bpl.publisher WHERE bpl.book = b.id) as publisher,
               (SELECT group_concat(l.lang_code, ',') FROM books_languages_link bll
                JOIN languages l ON l.id = bll.lang_code WHERE bll.book = b.id) as language
        FROM books b ORDER BY b.id DESC LIMIT ?
    """,
        (limit,),
    )

    imported = 0
    skipped = 0
    errors = []

    for row in cur.fetchall():
        title = row["title"]
        book_path = os.path.join(calibre_path, row["path"]) if row["path"] else None

        # Find actual file
        file_path = None
        if row["formats"] and book_path:
            for fmt_entry in row["formats"].split("|"):
                parts = fmt_entry.split(":")
                if len(parts) == 2:
                    fmt, name = parts
                    candidate = os.path.join(book_path, f"{name}.{fmt.lower()}")
                    if os.path.isfile(candidate):
                        file_path = candidate
                        break

        if not file_path:
            skipped += 1
            continue

        # Check if already imported (by title + first author)
        existing = await db.fetch_one("SELECT id FROM books WHERE title = $1 LIMIT 1", title)
        if existing:
            skipped += 1
            continue

        try:
            # Insert book
            book_row = await db.fetch_one(
                """INSERT INTO books (title, sort_title, isbn, description, language, quality_score)
                   VALUES ($1, $2, $3, $4, $5, 50) RETURNING id""",
                title,
                row["sort"] or title,
                row["isbn"] or None,
                row["description"],
                row["language"],
            )
            if book_row:
                book_id = book_row["id"]
                # Insert file reference
                fmt = os.path.splitext(file_path)[1].lstrip(".").lower()
                await db.execute(
                    "INSERT INTO book_files (book_id, file_path, format, file_name) VALUES ($1, $2, $3, $4)",
                    book_id,
                    file_path,
                    fmt,
                    os.path.basename(file_path),
                )
                # Insert authors
                if row["authors"]:
                    for author_name in row["authors"].split(", "):
                        a = await db.fetch_one(
                            "INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = $1 RETURNING id",
                            author_name,
                        )
                        if a:
                            await db.execute(
                                "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                book_id,
                                a["id"],
                            )
                imported += 1
        except Exception as e:
            errors.append(f"{title}: {e}")

    conn.close()
    return {"imported": imported, "skipped": skipped, "errors": errors[:10]}
