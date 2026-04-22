"""Import books from a Calibre library database (metadata.db).

Reads Calibre's SQLite database to extract:
- Books with metadata (title, author, ISBN, description, series, rating, tags)
- File paths for EPUB/PDF/MOBI
- Cover images
- Custom columns

Usage: point BrainyCat at a Calibre library directory and it will detect
metadata.db and offer to import.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any


def detect_calibre_library(path: str) -> bool:
    """Check if a directory is a Calibre library."""
    return os.path.isfile(os.path.join(path, "metadata.db"))


def read_calibre_db(path: str) -> list[dict[str, Any]]:
    """Read all books from a Calibre metadata.db."""
    db_path = os.path.join(path, "metadata.db")
    if not os.path.isfile(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    books = []
    for row in conn.execute("""
        SELECT b.id, b.title, b.sort as sort_title, b.isbn, b.path,
               b.pubdate, b.timestamp as added, b.last_modified,
               c.text as description, r.rating
        FROM books b
        LEFT JOIN comments c ON c.book = b.id
        LEFT JOIN books_ratings_link brl ON brl.book = b.id
        LEFT JOIN ratings r ON r.id = brl.rating
    """):
        book: dict[str, Any] = dict(row)

        # Authors
        authors = conn.execute(
            """
            SELECT a.name FROM authors a
            JOIN books_authors_link bal ON bal.author = a.id
            WHERE bal.book = ?
        """,
            (row["id"],),
        ).fetchall()
        book["authors"] = [a["name"] for a in authors]

        # Tags
        tags = conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN books_tags_link btl ON btl.tag = t.id
            WHERE btl.book = ?
        """,
            (row["id"],),
        ).fetchall()
        book["tags"] = [t["name"] for t in tags]

        # Series
        series = conn.execute(
            """
            SELECT s.name, bsl.book as series_index FROM series s
            JOIN books_series_link bsl ON bsl.series = s.id
            WHERE bsl.book = ?
        """,
            (row["id"],),
        ).fetchall()
        if series:
            book["series_name"] = series[0]["name"]

        # Publisher
        pubs = conn.execute(
            """
            SELECT p.name FROM publishers p
            JOIN books_publishers_link bpl ON bpl.publisher = p.id
            WHERE bpl.book = ?
        """,
            (row["id"],),
        ).fetchall()
        if pubs:
            book["publisher"] = pubs[0]["name"]

        # Languages
        langs = conn.execute(
            """
            SELECT l.lang_code FROM languages l
            JOIN books_languages_link bll ON bll.lang_code = l.id
            WHERE bll.book = ?
        """,
            (row["id"],),
        ).fetchall()
        book["languages"] = [lang["lang_code"] for lang in langs]

        # File formats
        formats = conn.execute(
            """
            SELECT format, name, uncompressed_size FROM data WHERE book = ?
        """,
            (row["id"],),
        ).fetchall()
        book["formats"] = [{"format": f["format"].lower(), "name": f["name"], "size": f["uncompressed_size"]} for f in formats]

        # Resolve file paths
        book_dir = os.path.join(path, row["path"]) if row["path"] else None
        book["files"] = []
        if book_dir:
            for fmt in book["formats"]:
                fp = os.path.join(book_dir, f"{fmt['name']}.{fmt['format']}")
                if os.path.isfile(fp):
                    book["files"].append({"path": fp, "format": fmt["format"]})

            # Cover
            cover_path = os.path.join(book_dir, "cover.jpg")
            if os.path.isfile(cover_path):
                book["cover_path"] = cover_path

        # Custom columns
        try:
            customs = {}
            for cc in conn.execute("SELECT id, label, name, datatype FROM custom_columns"):
                table = f"custom_column_{cc['id']}"
                try:
                    vals = conn.execute(
                        f"""
                        SELECT value FROM {table} WHERE book = ?
                    """,
                        (row["id"],),
                    ).fetchall()
                    if vals:
                        customs[cc["label"]] = vals[0]["value"] if len(vals) == 1 else [v["value"] for v in vals]
                except sqlite3.OperationalError:
                    pass
            if customs:
                book["custom_columns"] = customs
        except sqlite3.OperationalError:
            pass

        books.append(book)

    conn.close()
    return books


def calibre_library_stats(path: str) -> dict[str, Any]:
    """Quick stats about a Calibre library without reading all books."""
    db_path = os.path.join(path, "metadata.db")
    if not os.path.isfile(db_path):
        return {"error": "not a Calibre library"}

    conn = sqlite3.connect(db_path)
    stats: dict[str, Any] = {}
    stats["books"] = conn.execute("SELECT count(*) FROM books").fetchone()[0]
    stats["authors"] = conn.execute("SELECT count(*) FROM authors").fetchone()[0]
    stats["tags"] = conn.execute("SELECT count(*) FROM tags").fetchone()[0]
    stats["series"] = conn.execute("SELECT count(*) FROM series").fetchone()[0]
    stats["formats"] = [r[0] for r in conn.execute("SELECT DISTINCT format FROM data").fetchall()]
    stats["custom_columns"] = [
        {"label": r[1], "name": r[2], "type": r[3]} for r in conn.execute("SELECT id, label, name, datatype FROM custom_columns")
    ]
    conn.close()
    return stats
