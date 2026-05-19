"""Audiobook grouping — detect multi-file audiobooks and import as one book.

When multiple audio files share a common prefix or were in the same directory,
group them as a single audiobook with multiple files (chapters).
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any
from uuid import uuid4

from brainycat.db import execute, fetch_one
from brainycat.logging import log
from brainycat.watcher import ALLOWED_EXT

AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".opus"}


def _extract_group_key(filename: str) -> str | None:
    """Extract a grouping key from an audio filename.

    Strips track numbers, CD numbers, disc indicators to find the common title.
    E.g.: "Harry Potter 1 - CD01.mp3" → "Harry Potter 1"
          "01 - Chapter One.mp3" → None (too generic)
    """
    name = os.path.splitext(filename)[0]
    # Remove common track/CD patterns
    name = re.sub(r"[\s_-]*(?:CD|Disc|Part|Track|Chapter|Chapitre)[\s_-]*\d+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\s_-]*\d{1,3}\s*$", "", name)  # trailing numbers
    name = re.sub(r"^\d{1,3}[\s_.-]+", "", name)  # leading track numbers
    name = name.strip(" _-")
    # Only group if the remaining title is meaningful (>5 chars)
    return name if len(name) > 5 else None


def find_audio_groups(incoming_dir: str) -> dict[str, list[str]]:
    """Scan incoming for audio files that should be grouped as one audiobook."""
    audio_files: list[tuple[str, str]] = []  # (group_key, filepath)

    for entry in os.scandir(incoming_dir):
        if not entry.is_file():
            continue
        ext = os.path.splitext(entry.name)[1].lower()
        if ext not in AUDIO_EXT:
            continue
        key = _extract_group_key(entry.name)
        if key:
            audio_files.append((key, entry.path))

    # Group by key, only keep groups with 2+ files
    groups: dict[str, list[str]] = defaultdict(list)
    for key, path in audio_files:
        groups[key].append(path)

    return {k: sorted(v) for k, v in groups.items() if len(v) >= 2}


async def import_audio_group(title: str, files: list[str]) -> dict[str, Any]:
    """Import a group of audio files as a single audiobook."""
    from brainycat.extract import extract_metadata
    from brainycat.storage import book_dir

    book_id = uuid4()
    bdir = book_dir(str(book_id))
    os.makedirs(bdir, exist_ok=True)

    # Extract metadata from first file
    meta = extract_metadata(files[0])
    clean_title = title.replace("_", " ").strip()

    await execute(
        "INSERT INTO books (id, title, created_at, updated_at) VALUES ($1, $2, now(), now())",
        book_id, clean_title,
    )

    # Move all files and create book_files entries
    import shutil
    total_duration = 0.0
    for i, src in enumerate(files):
        fname = os.path.basename(src)
        dst = os.path.join(bdir, fname)
        shutil.move(src, dst)
        size = os.path.getsize(dst)
        ext = os.path.splitext(fname)[1].lower().lstrip(".")

        await execute(
            "INSERT INTO book_files (book_id, file_path, format, file_size, file_name) VALUES ($1, $2, $3, $4, $5)",
            book_id, dst, ext, size, fname,
        )

    # Link author if found in metadata
    author = meta.get("author") or meta.get("artist")
    if author:
        await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", author)
        row = await fetch_one("SELECT id FROM authors WHERE name = $1", author)
        if row:
            await execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                          book_id, row["id"])

    await log.ainfo("audiobook_imported", title=clean_title[:50], files=len(files))
    return {"ok": True, "book_id": str(book_id), "title": clean_title, "files": len(files)}
