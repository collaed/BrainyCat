"""Incoming folder scanner — watch for new files, parse, propose metadata."""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import UUID, uuid4

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.logging import log


def parse_filename(filename: str) -> dict[str, str | None]:
    """Extract author and title from common filename patterns."""
    name = os.path.splitext(filename)[0]
    # Pattern: "Author - Title"
    m = re.match(r"^(.+?)\s*[-\u2013\u2014]\s*(.+)$", name)
    if m:
        return {"author": m.group(1).strip(), "title": m.group(2).strip()}
    return {"author": None, "title": name.strip()}


async def scan_incoming() -> list[dict[str, Any]]:
    """Scan incoming directory for new files."""
    incoming_dir = settings.incoming_dir
    if not os.path.isdir(incoming_dir):
        return []

    results = []
    for entry in os.scandir(incoming_dir):
        if not entry.is_file():
            continue
        ext = os.path.splitext(entry.name)[1].lower()
        if ext not in {".epub", ".pdf", ".mobi", ".mp3", ".m4b", ".m4a", ".opus", ".flac", ".ogg"}:
            continue
        # Skip already processed
        existing = await fetch_one("SELECT id FROM incoming_items WHERE file_path = $1", entry.path)
        if existing:
            continue

        parsed = parse_filename(entry.name)
        iid = uuid4()
        await execute(
            """INSERT INTO incoming_items (id, file_path, file_name, file_size, parsed_title, parsed_author)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            iid,
            entry.path,
            entry.name,
            entry.stat().st_size,
            parsed["title"],
            parsed["author"],
        )
        results.append({"id": str(iid), "file_name": entry.name, **parsed})
        await log.ainfo("incoming_scanned", file=entry.name)

    return results


async def list_incoming(status: str | None = None) -> list[dict[str, Any]]:
    """List incoming items, optionally filtered by status."""
    if status:
        rows = await fetch_all("SELECT * FROM incoming_items WHERE status = $1 ORDER BY created_at DESC", status)
    else:
        rows = await fetch_all("SELECT * FROM incoming_items ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def confirm_incoming(item_id: str) -> dict[str, Any]:
    """Confirm an incoming item — import into library."""
    row = await fetch_one("SELECT * FROM incoming_items WHERE id = $1", UUID(item_id))
    if not row:
        return {"error": "not found"}

    from brainycat.extract import extract_metadata
    from brainycat.storage import book_dir

    meta = extract_metadata(row["file_path"])
    title = meta.get("title") or row["parsed_title"] or row["file_name"]
    book_id = str(uuid4())

    # Move file to library
    dest_dir = book_dir(book_id)
    dest_path = os.path.join(dest_dir, row["file_name"])
    os.rename(row["file_path"], dest_path)

    # Create book record (reuse books.upload_book logic inline)
    await execute(
        "INSERT INTO books (id, title, isbn, description) VALUES ($1,$2,$3,$4)",
        UUID(book_id),
        title,
        meta.get("isbn"),
        meta.get("description"),
    )
    await execute(
        """INSERT INTO book_files (book_id, format, file_path, file_name, file_size)
           VALUES ($1,$2,$3,$4,$5)""",
        UUID(book_id),
        meta.get("format", "unknown"),
        dest_path,
        row["file_name"],
        row["file_size"],
    )
    await execute(
        "UPDATE incoming_items SET status = 'confirmed', matched_book_id = $1 WHERE id = $2",
        UUID(book_id),
        UUID(item_id),
    )

    return {"book_id": book_id, "title": title}


async def reject_incoming(item_id: str) -> dict[str, bool]:
    """Reject an incoming item."""
    await execute("UPDATE incoming_items SET status = 'rejected' WHERE id = $1", UUID(item_id))
    return {"ok": True}
