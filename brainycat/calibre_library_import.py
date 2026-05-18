"""Import metadata from a Calibre library's OPF files into BrainyCat.

Reads Author/Title/metadata.opf + cover.jpg from a mounted Calibre library,
matches against existing books by title similarity, and enriches with the OPF data.
"""

from __future__ import annotations

import os
import shutil
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

from brainycat.db import execute, fetch_one
from brainycat.filename_history import record_rename

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}

CALIBRE_PATH = "/data/calibre-library"


def _parse_opf(opf_path: str) -> dict[str, Any]:
    """Extract metadata from a Calibre OPF file."""
    tree = ET.parse(opf_path)
    root = tree.getroot()
    meta = root.find("opf:metadata", NS) or root.find("{http://www.idpf.org/2007/opf}metadata")
    if meta is None:
        return {}

    def _text(tag: str) -> str | None:
        el = meta.find(f"dc:{tag}", NS) or meta.find(f"{{http://purl.org/dc/elements/1.1/}}{tag}")
        return el.text.strip() if el is not None and el.text else None

    def _all_text(tag: str) -> list[str]:
        els = meta.findall(f"dc:{tag}", NS) or meta.findall(f"{{http://purl.org/dc/elements/1.1/}}{tag}")
        return [el.text.strip() for el in els if el.text]

    return {
        "title": _text("title"),
        "authors": _all_text("creator"),
        "description": _text("description"),
        "publisher": _text("publisher"),
        "language": _text("language"),
        "date": _text("date"),
        "subjects": _all_text("subject"),
    }


async def import_calibre_library(limit: int = 0) -> dict[str, Any]:
    """Walk the Calibre library, import books with their OPF metadata."""
    if not os.path.isdir(CALIBRE_PATH):
        return {"error": "Calibre library not mounted at " + CALIBRE_PATH}

    imported, skipped, matched = 0, 0, 0
    count = 0

    for author_dir in sorted(os.scandir(CALIBRE_PATH), key=lambda e: e.name):
        if not author_dir.is_dir() or author_dir.name.startswith("."):
            continue
        for book_dir_entry in sorted(os.scandir(author_dir.path), key=lambda e: e.name):
            if not book_dir_entry.is_dir():
                continue
            if limit and count >= limit:
                break

            opf_path = os.path.join(book_dir_entry.path, "metadata.opf")
            if not os.path.isfile(opf_path):
                skipped += 1
                continue

            meta = _parse_opf(opf_path)
            title = meta.get("title")
            if not title:
                skipped += 1
                continue

            # Find the book file
            book_file = None
            for f in os.scandir(book_dir_entry.path):
                if f.is_file() and f.name.rsplit(".", 1)[-1].lower() in ("epub", "pdf", "mobi", "azw3"):
                    book_file = f
                    break

            if not book_file:
                skipped += 1
                continue

            # Check if already imported (title similarity)
            existing = await fetch_one(
                "SELECT id FROM books WHERE title % $1 AND similarity(title, $1) > 0.6 LIMIT 1",
                title,
            )
            if existing:
                # Enrich existing book with Calibre metadata
                await _apply_calibre_metadata(str(existing["id"]), meta, book_dir_entry.path)
                matched += 1
                count += 1
                continue

            # Import as new book
            book_id = uuid4()
            ext = os.path.splitext(book_file.name)[1].lower()

            from brainycat.storage import book_dir

            bdir = book_dir(str(book_id))
            os.makedirs(bdir, exist_ok=True)
            dst = os.path.join(bdir, book_file.name)
            shutil.copy2(book_file.path, dst)

            # Cover
            cover_src = os.path.join(book_dir_entry.path, "cover.jpg")
            cover_path = None
            if os.path.isfile(cover_src):
                cover_path = os.path.join(bdir, "cover.jpg")
                shutil.copy2(cover_src, cover_path)

            await execute(
                "INSERT INTO books (id, title, cover_path, description, publisher, pubdate, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, now(), now())",
                book_id, title, cover_path,
                meta.get("description"), meta.get("publisher"),
                meta.get("date"),
            )
            await execute(
                "INSERT INTO book_files (book_id, file_path, format, file_size, file_name) VALUES ($1, $2, $3, $4, $5)",
                book_id, dst, ext.lstrip("."), os.path.getsize(dst), book_file.name,
            )

            # Authors
            for author_name in meta.get("authors", []):
                await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", author_name)
                arow = await fetch_one("SELECT id FROM authors WHERE name = $1", author_name)
                if arow:
                    await execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                  book_id, arow["id"])

            # Language
            lang = meta.get("language")
            if lang:
                await execute("INSERT INTO languages (code) VALUES ($1) ON CONFLICT DO NOTHING", lang)
                lrow = await fetch_one("SELECT id FROM languages WHERE code = $1", lang)
                if lrow:
                    await execute("INSERT INTO books_languages (book_id, language_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                  book_id, lrow["id"])

            # Tags/subjects
            for subj in meta.get("subjects", []):
                await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", subj)
                trow = await fetch_one("SELECT id FROM tags WHERE name = $1", subj)
                if trow:
                    await execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                  book_id, trow["id"])

            # Record filename history
            await record_rename(str(book_id), "calibre_import", book_file.name, f"{title}{ext}")

            imported += 1
            count += 1

        if limit and count >= limit:
            break

    return {"imported": imported, "matched_enriched": matched, "skipped": skipped}


async def _apply_calibre_metadata(book_id: str, meta: dict, book_dir_path: str) -> None:
    """Apply Calibre OPF metadata to an existing book."""
    from uuid import UUID

    sets, vals = [], []
    idx = 1

    book = await fetch_one("SELECT * FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return

    if meta.get("description") and not book.get("description"):
        sets.append(f"description = ${idx}")
        vals.append(meta["description"])
        idx += 1
    if meta.get("publisher") and not book.get("publisher"):
        # publisher is in extra_metadata
        pass

    if sets:
        vals.append(UUID(book_id))
        await execute(f"UPDATE books SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)

    # Cover if missing
    if not book.get("cover_path"):
        cover_src = os.path.join(book_dir_path, "cover.jpg")
        if os.path.isfile(cover_src):
            from brainycat.storage import book_dir

            bdir = book_dir(book_id)
            os.makedirs(bdir, exist_ok=True)
            cover_dst = os.path.join(bdir, "cover.jpg")
            shutil.copy2(cover_src, cover_dst)
            await execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_dst, UUID(book_id))

    # Authors if missing
    existing_author = await fetch_one(
        "SELECT 1 FROM books_authors WHERE book_id = $1", UUID(book_id))
    if not existing_author:
        for author_name in meta.get("authors", []):
            await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", author_name)
            arow = await fetch_one("SELECT id FROM authors WHERE name = $1", author_name)
            if arow:
                await execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                              UUID(book_id), arow["id"])
