"""Import books from a Calibre library database (metadata.db).

Handles all schema versions (v1-v26+):
- v1-v17: books.isbn exists, no identifiers table
- v18-v25: books.isbn exists (legacy, may be stale), identifiers table has ISBNs
- v26+: books.isbn column DROPPED, identifiers table is only ISBN source

Detection: PRAGMA user_version + PRAGMA table_info + sqlite_master
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any


def detect_calibre_library(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "metadata.db"))


def _detect_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    """Detect Calibre schema version and available features."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    book_cols = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    return {
        "version": version,
        "has_isbn_col": "isbn" in book_cols,
        "has_series_index": "series_index" in book_cols,
        "has_identifiers": "identifiers" in tables,
        "has_annotations": "annotations" in tables,
        "has_last_read": "last_read_positions" in tables,
        "has_uuid": "uuid" in book_cols,
        "has_author_sort": "author_sort" in book_cols,
    }


def read_calibre_db(path: str) -> list[dict[str, Any]]:
    db_path = os.path.join(path, "metadata.db")
    if not os.path.isfile(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    schema = _detect_schema(conn)

    # Build SELECT dynamically based on available columns
    cols = ["b.id", "b.title", "b.sort as sort_title", "b.path", "b.pubdate", "b.timestamp as added", "b.last_modified"]
    if schema["has_isbn_col"]:
        cols.append("b.isbn as legacy_isbn")
    if schema["has_series_index"]:
        cols.append("b.series_index")
    if schema["has_uuid"]:
        cols.append("b.uuid")
    if schema["has_author_sort"]:
        cols.append("b.author_sort")

    books = []
    for row in conn.execute(f"""
        SELECT {", ".join(cols)},
               c.text as description, r.rating
        FROM books b
        LEFT JOIN comments c ON c.book = b.id
        LEFT JOIN books_ratings_link brl ON brl.book = b.id
        LEFT JOIN ratings r ON r.id = brl.rating
    """):
        book: dict[str, Any] = dict(row)
        bid = row["id"]

        # ISBN: identifiers table (v18+) > books.isbn (v1-v25)
        isbn = None
        if schema["has_identifiers"]:
            r = conn.execute("SELECT val FROM identifiers WHERE book=? AND type='isbn'", (bid,)).fetchone()
            if r:
                isbn = r[0]
        if not isbn and schema["has_isbn_col"]:
            isbn = row["legacy_isbn"] if "legacy_isbn" in dict(row) else None
        book["isbn"] = isbn

        # All identifiers (v18+)
        book["identifiers"] = {}
        if schema["has_identifiers"]:
            for ident in conn.execute("SELECT type, val FROM identifiers WHERE book=?", (bid,)):
                book["identifiers"][ident["type"]] = ident["val"]

        # Authors with sort
        book["authors"] = [
            {"name": a["name"], "sort": a["sort"]}
            for a in conn.execute(
                """
                SELECT a.name, a.sort FROM authors a
                JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=?
            """,
                (bid,),
            )
        ]

        # Tags
        book["tags"] = [
            t["name"]
            for t in conn.execute(
                """
                SELECT t.name FROM tags t
                JOIN books_tags_link btl ON btl.tag=t.id WHERE btl.book=?
            """,
                (bid,),
            )
        ]

        # Series — name from series table, index from books.series_index
        for s in conn.execute(
            """
            SELECT s.name FROM series s
            JOIN books_series_link bsl ON bsl.series=s.id WHERE bsl.book=?
        """,
            (bid,),
        ):
            book["series_name"] = s["name"]
            book["series_index"] = row["series_index"] if schema["has_series_index"] else 1

        # Publisher
        for p in conn.execute(
            """
            SELECT p.name FROM publishers p
            JOIN books_publishers_link bpl ON bpl.publisher=p.id WHERE bpl.book=?
        """,
            (bid,),
        ):
            book["publisher"] = p["name"]

        # Languages
        book["languages"] = [
            lang["lang_code"]
            for lang in conn.execute(
                """
                SELECT l.lang_code FROM languages l
                JOIN books_languages_link bll ON bll.lang_code=l.id WHERE bll.book=?
            """,
                (bid,),
            )
        ]

        # Files
        book["formats"] = [
            {"format": f["format"].lower(), "name": f["name"], "size": f["uncompressed_size"]}
            for f in conn.execute("SELECT format, name, uncompressed_size FROM data WHERE book=?", (bid,))
        ]
        book_dir = os.path.join(path, row["path"]) if row["path"] else None
        book["files"] = []
        if book_dir:
            for fmt in book["formats"]:
                fp = os.path.join(book_dir, f"{fmt['name']}.{fmt['format']}")
                if os.path.isfile(fp):
                    book["files"].append({"path": fp, "format": fmt["format"]})
            cover = os.path.join(book_dir, "cover.jpg")
            if os.path.isfile(cover):
                book["cover_path"] = cover

        # Annotations (v23+)
        book["annotations"] = []
        if schema["has_annotations"]:
            for ann in conn.execute(
                "SELECT format, annotation_type, annotation_data FROM annotations WHERE book=?",
                (bid,),
            ):
                book["annotations"].append({"format": ann["format"], "type": ann["annotation_type"], "data": ann["annotation_data"]})

        # Reading positions (v22+)
        book["reading_positions"] = []
        if schema["has_last_read"]:
            for pos in conn.execute(
                "SELECT format, user, device, cfi, epoch, pos_frac FROM last_read_positions WHERE book=?",
                (bid,),
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
                    vals = conn.execute(f"SELECT value FROM {table} WHERE book=?", (bid,)).fetchall()
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
    db_path = os.path.join(path, "metadata.db")
    if not os.path.isfile(db_path):
        return {"error": "not a Calibre library"}

    conn = sqlite3.connect(db_path)
    schema = _detect_schema(conn)
    stats: dict[str, Any] = {"schema": schema}
    stats["books"] = conn.execute("SELECT count(*) FROM books").fetchone()[0]
    stats["authors"] = conn.execute("SELECT count(*) FROM authors").fetchone()[0]
    stats["tags"] = conn.execute("SELECT count(*) FROM tags").fetchone()[0]
    stats["series"] = conn.execute("SELECT count(*) FROM series").fetchone()[0]
    stats["formats"] = [r[0] for r in conn.execute("SELECT DISTINCT format FROM data")]
    if schema["has_identifiers"]:
        stats["identifiers"] = conn.execute("SELECT count(*) FROM identifiers").fetchone()[0]
        stats["identifier_types"] = [r[0] for r in conn.execute("SELECT DISTINCT type FROM identifiers")]
    if schema["has_annotations"]:
        stats["annotations"] = conn.execute("SELECT count(*) FROM annotations").fetchone()[0]
    stats["custom_columns"] = [
        {"label": r[1], "name": r[2], "type": r[3]} for r in conn.execute("SELECT id, label, name, datatype FROM custom_columns")
    ]
    conn.close()
    return stats
