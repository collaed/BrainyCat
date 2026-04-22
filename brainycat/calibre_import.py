"""Import books from a Calibre library database (metadata.db).

Reads Calibre's SQLite database to extract:
- Books with metadata (title, author, ISBN, description, series, rating, tags)
- Identifiers (ISBN, ASIN, DOI, Google Books ID, etc.)
- Series with correct series_index from books table
- File paths for EPUB/PDF/MOBI
- Cover images
- Custom columns
- Annotations and reading positions
- Author sort names and UUIDs
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

    # Detect schema version — isbn column was dropped in v26
    columns = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    has_isbn_col = "isbn" in columns

    # Check which tables exist
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    has_identifiers = "identifiers" in tables
    has_annotations = "annotations" in tables
    has_last_read = "last_read_positions" in tables

    books = []
    # series_index is on the books table, NOT on books_series_link
    isbn_col = "b.isbn," if has_isbn_col else ""
    for row in conn.execute(f"""
        SELECT b.id, b.title, b.sort as sort_title, b.author_sort,
               b.series_index, b.uuid, b.path, {isbn_col}
               b.pubdate, b.timestamp as added, b.last_modified,
               c.text as description, r.rating
        FROM books b
        LEFT JOIN comments c ON c.book = b.id
        LEFT JOIN books_ratings_link brl ON brl.book = b.id
        LEFT JOIN ratings r ON r.id = brl.rating
    """):
        book: dict[str, Any] = dict(row)
        book_id = row["id"]

        # ISBN from identifiers table (modern Calibre) or books.isbn (legacy)
        isbn = None
        if has_isbn_col:
            isbn = row.get("isbn", None)
        if not isbn and has_identifiers:
            isbn_row = conn.execute(
                "SELECT val FROM identifiers WHERE book = ? AND type = 'isbn'",
                (book_id,),
            ).fetchone()
            if isbn_row:
                isbn = isbn_row["val"]
        book["isbn"] = isbn

        # All identifiers (ASIN, DOI, Google Books, etc.)
        book["identifiers"] = {}
        if has_identifiers:
            for ident in conn.execute("SELECT type, val FROM identifiers WHERE book = ?", (book_id,)):
                book["identifiers"][ident["type"]] = ident["val"]

        # Authors with sort names
        authors = conn.execute(
            """
            SELECT a.name, a.sort as author_sort FROM authors a
            JOIN books_authors_link bal ON bal.author = a.id
            WHERE bal.book = ?
        """,
            (book_id,),
        ).fetchall()
        book["authors"] = [{"name": a["name"], "sort": a["author_sort"]} for a in authors]

        # Tags
        tags = conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN books_tags_link btl ON btl.tag = t.id
            WHERE btl.book = ?
        """,
            (book_id,),
        ).fetchall()
        book["tags"] = [t["name"] for t in tags]

        # Series — name from series table, index from books.series_index
        series = conn.execute(
            """
            SELECT s.name FROM series s
            JOIN books_series_link bsl ON bsl.series = s.id
            WHERE bsl.book = ?
        """,
            (book_id,),
        ).fetchall()
        if series:
            book["series_name"] = series[0]["name"]
            book["series_index"] = row["series_index"]  # Correct: from books table

        # Publisher
        pubs = conn.execute(
            """
            SELECT p.name FROM publishers p
            JOIN books_publishers_link bpl ON bpl.publisher = p.id
            WHERE bpl.book = ?
        """,
            (book_id,),
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
            (book_id,),
        ).fetchall()
        book["languages"] = [lang["lang_code"] for lang in langs]

        # File formats
        formats = conn.execute(
            "SELECT format, name, uncompressed_size FROM data WHERE book = ?",
            (book_id,),
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
            cover_path = os.path.join(book_dir, "cover.jpg")
            if os.path.isfile(cover_path):
                book["cover_path"] = cover_path

        # Annotations (highlights, bookmarks) — Calibre 5+
        book["annotations"] = []
        if has_annotations:
            for ann in conn.execute(
                "SELECT format, annotation_type, annotation_data FROM annotations WHERE book = ?",
                (book_id,),
            ):
                book["annotations"].append(
                    {
                        "format": ann["format"],
                        "type": ann["annotation_type"],
                        "data": ann["annotation_data"],
                    }
                )

        # Reading positions — Calibre 5+
        book["reading_positions"] = []
        if has_last_read:
            for pos in conn.execute(
                "SELECT format, user, device, cfi, epoch, pos_frac FROM last_read_positions WHERE book = ?",
                (book_id,),
            ):
                book["reading_positions"].append(
                    {
                        "format": pos["format"],
                        "user": pos["user"],
                        "device": pos["device"],
                        "cfi": pos["cfi"],
                        "position_frac": pos["pos_frac"],
                    }
                )

        # Custom columns
        try:
            customs = {}
            for cc in conn.execute("SELECT id, label, name, datatype FROM custom_columns"):
                table = f"custom_column_{cc['id']}"
                try:
                    vals = conn.execute(f"SELECT value FROM {table} WHERE book = ?", (book_id,)).fetchall()
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
    """Quick stats about a Calibre library."""
    db_path = os.path.join(path, "metadata.db")
    if not os.path.isfile(db_path):
        return {"error": "not a Calibre library"}

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    stats: dict[str, Any] = {}
    stats["books"] = conn.execute("SELECT count(*) FROM books").fetchone()[0]
    stats["authors"] = conn.execute("SELECT count(*) FROM authors").fetchone()[0]
    stats["tags"] = conn.execute("SELECT count(*) FROM tags").fetchone()[0]
    stats["series"] = conn.execute("SELECT count(*) FROM series").fetchone()[0]
    stats["formats"] = [r[0] for r in conn.execute("SELECT DISTINCT format FROM data").fetchall()]
    if "identifiers" in tables:
        stats["identifiers"] = conn.execute("SELECT count(*) FROM identifiers").fetchone()[0]
        stats["identifier_types"] = [r[0] for r in conn.execute("SELECT DISTINCT type FROM identifiers").fetchall()]
    if "annotations" in tables:
        stats["annotations"] = conn.execute("SELECT count(*) FROM annotations").fetchone()[0]
    stats["custom_columns"] = [
        {"label": r[1], "name": r[2], "type": r[3]} for r in conn.execute("SELECT id, label, name, datatype FROM custom_columns")
    ]
    conn.close()
    return stats
