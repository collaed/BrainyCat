"""eKitaab-style file renaming: rename book files to 'Author - Title [ISBN].ext'.

Runs automatically after enrichment updates a book's metadata (brainycat.metadata.enrich_book) —
makes the /data/books/ folder human-browsable and gives downloads a clean, standardized filename
even without this (brainycat.filenames.build_filename computes it fresh at download time too).
"""

from __future__ import annotations

import os
from uuid import UUID

from brainycat.filenames import build_filename, safe_filename
from brainycat.title_confidence import is_unresolved_title

__all__ = ["safe_filename", "rename_book_file"]


async def rename_book_file(book_id: str) -> dict | None:
    """Rename every file of a book to the standardized pattern. Skips (does not overwrite) if the
    target name is already taken by a different book's file. Also skips entirely while the title
    is unresolved ("Unknown"/"Untitled"/a raw ISBN/a hash fragment) — the original download
    filename is often the only place real title/author info survives for these books (see the
    "unresolved_title" flag surfaced in the Quality Issues list), so renaming it away before
    enrichment has actually identified the book would destroy that signal."""
    from brainycat.db import execute, fetch_all, fetch_one
    from brainycat.filename_history import record_rename

    bid = UUID(book_id)
    book = await fetch_one(
        """SELECT b.title, b.isbn, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
           FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE b.id = $1 GROUP BY b.id""",
        bid,
    )
    if not book or is_unresolved_title(book["title"]):
        return None

    files = await fetch_all("SELECT id, file_path, file_name FROM book_files WHERE book_id = $1", bid)
    renamed = []
    for f in files:
        if not f["file_path"] or not os.path.isfile(f["file_path"]):
            continue
        ext = os.path.splitext(f["file_path"])[1]
        new_name = build_filename(book["title"], book["authors"], book["isbn"], ext)
        new_path = os.path.join(os.path.dirname(f["file_path"]), new_name)

        if new_path == f["file_path"]:
            continue
        if os.path.exists(new_path):
            continue  # name collision — leave this file alone rather than risk overwriting another book's file

        old_name = f["file_name"]
        os.rename(f["file_path"], new_path)
        await execute("UPDATE book_files SET file_path = $1, file_name = $2 WHERE id = $3", new_path, new_name, f["id"])
        await record_rename(book_id, "auto_standardize", old_name, new_name)
        renamed.append({"old": old_name, "new": new_name})

    return {"renamed": renamed} if renamed else None
