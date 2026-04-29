"""eKitaab-style file renaming: rename book files to include title+author+ISBN.

Makes the /data/books/ folder human-browsable without the app.
Only runs when BRAINYCAT_EXP_FILE_RENAME=1.

Config: BRAINYCAT_EXP_FILE_RENAME=1
"""

from __future__ import annotations

import os
import re


def safe_filename(s: str, max_len: int = 60) -> str:
    """Sanitize string for use in filename."""
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = s.strip(". ")
    return s[:max_len]


async def rename_book_file(book_id: str) -> dict | None:
    """Rename a book's file to 'Author - Title [ISBN].ext' format."""
    from brainycat.db import execute, fetch_one

    book = await fetch_one(
        "SELECT b.title, b.author, b.isbn, bf.file_path, bf.id as file_id "
        "FROM books b JOIN book_files bf ON bf.book_id = b.id "
        "WHERE b.id = $1 LIMIT 1",
        book_id,
    )
    if not book or not book["file_path"] or not os.path.isfile(book["file_path"]):
        return None

    title = safe_filename(book["title"] or "Unknown")
    author = safe_filename(book["author"] or "Unknown")
    isbn = book["isbn"] or ""
    ext = os.path.splitext(book["file_path"])[1]

    new_name = f"{author} - {title}"
    if isbn:
        new_name += f" [{isbn}]"
    new_name += ext

    new_path = os.path.join(os.path.dirname(book["file_path"]), new_name)
    if new_path == book["file_path"]:
        return None

    os.rename(book["file_path"], new_path)
    await execute("UPDATE book_files SET file_path = $1 WHERE id = $2", new_path, book["file_id"])
    return {"old": book["file_path"], "new": new_path}
