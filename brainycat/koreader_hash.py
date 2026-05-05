"""Generate KOReader-compatible partial MD5 hash for book files.

KOReader identifies books by MD5 of the first 10KB + file size.
We compute this on ingest so kosync works without OPDS download.
"""

from __future__ import annotations

import hashlib
import os

from brainycat import db


def compute_koreader_hash(file_path: str) -> str | None:
    """Compute KOReader's partial MD5 (first 10KB of file)."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(10240)  # 10KB
        return hashlib.md5(chunk).hexdigest()
    except Exception:
        return None


async def store_hash(book_id: str, file_path: str) -> str | None:
    """Compute and store KOReader hash for a book file."""
    from uuid import UUID

    h = compute_koreader_hash(file_path)
    if h:
        await db.execute(
            "UPDATE book_files SET koreader_hash = $1 WHERE book_id = $2 AND file_path = $3",
            h,
            UUID(book_id),
            file_path,
        )
    return h


async def backfill_hashes(limit: int = 100) -> int:
    """Backfill KOReader hashes for files that don't have one."""
    import os

    rows = await db.fetch_all(
        "SELECT book_id, file_path FROM book_files WHERE koreader_hash IS NULL AND format IN ('epub', 'pdf', 'mobi', 'azw3', 'kepub') LIMIT $1",
        limit,
    )
    computed = 0
    for r in rows:
        if os.path.isfile(r["file_path"]):
            h = compute_koreader_hash(r["file_path"])
            if h:
                await db.execute(
                    "UPDATE book_files SET koreader_hash = $1 WHERE book_id = $2 AND file_path = $3",
                    h,
                    r["book_id"],
                    r["file_path"],
                )
                computed += 1
    return computed
