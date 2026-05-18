"""Organize books into Genre/Author/Title tree after successful enrichment."""

from __future__ import annotations

import os
import re
import shutil
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.filename_history import record_rename


def _safe_name(s: str, max_len: int = 80) -> str:
    """Sanitize a string for use as a directory/file name."""
    s = re.sub(r'[<>:"/\\|?*]', '', s)
    s = s.strip('. ')
    return s[:max_len] if s else "Unknown"


async def organize_after_enrichment(book_id: str) -> dict:
    """Move book file from flat storage into Genre/Author/Title tree."""
    from brainycat.config import settings

    book = await fetch_one("SELECT id, title FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return {"moved": False}

    file_row = await fetch_one(
        "SELECT id, file_path, file_name, format FROM book_files WHERE book_id = $1 ORDER BY created_at LIMIT 1",
        UUID(book_id),
    )
    if not file_row or not file_row["file_path"] or not os.path.isfile(file_row["file_path"]):
        return {"moved": False}

    # Get genre (first tag)
    tag = await fetch_one(
        "SELECT t.name FROM tags t JOIN books_tags bt ON bt.tag_id = t.id WHERE bt.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    genre = _safe_name(tag["name"]) if tag else "Unsorted"

    # Get author
    author_row = await fetch_one(
        "SELECT a.name FROM authors a JOIN books_authors ba ON ba.author_id = a.id WHERE ba.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    author = _safe_name(author_row["name"]) if author_row else "Unknown Author"

    # Build destination path
    title = _safe_name(book["title"])
    ext = os.path.splitext(file_row["file_name"])[1] if file_row["file_name"] else f".{file_row['format']}"
    dest_filename = f"{title}{ext}"

    data_dir = getattr(settings, "data_dir", "/data")
    dest_dir = os.path.join(data_dir, "library", genre, author)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, dest_filename)

    # Avoid overwriting
    if os.path.exists(dest_path):
        base, e = os.path.splitext(dest_path)
        dest_path = f"{base}_{str(book['id'])[:8]}{e}"
        dest_filename = os.path.basename(dest_path)

    src_path = file_row["file_path"]
    old_filename = os.path.basename(src_path)

    shutil.move(src_path, dest_path)

    # Update DB
    await execute("UPDATE book_files SET file_path = $1, file_name = $2 WHERE id = $3",
                  dest_path, dest_filename, file_row["id"])

    # Record in filename history
    await record_rename(book_id, "organize", old_filename, f"{genre}/{author}/{dest_filename}")

    return {"moved": True, "path": f"{genre}/{author}/{dest_filename}"}
