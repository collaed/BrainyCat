"""File watcher — auto-import books dropped into the incoming folder."""

from __future__ import annotations

import asyncio
import os

from brainycat.config import settings
from brainycat.logging import log

ALLOWED_EXT = {
    ".epub",
    ".pdf",
    ".mobi",
    ".azw3",
    ".kfx",
    ".fb2",
    ".docx",
    ".odt",
    ".txt",
    ".rtf",
    ".html",
    ".md",
    ".cbz",
    ".cbr",
    ".djvu",
    ".mp3",
    ".m4b",
    ".m4a",
    ".flac",
    ".ogg",
    ".zip",
}
IGNORE_EXT = {".part", ".tmp", ".crdownload", ".downloading"}


async def watch_incoming() -> None:
    """Poll incoming folder for new files and auto-import them."""
    incoming = settings.incoming_dir
    if not os.path.isdir(incoming):
        os.makedirs(incoming, exist_ok=True)

    seen: set[str] = set()

    while True:
        try:
            files = []
            for entry in os.scandir(incoming):
                if entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in IGNORE_EXT or entry.name.startswith("."):
                        continue
                    if ext not in ALLOWED_EXT:
                        continue
                    # Debounce: only process if file hasn't changed size in 5s
                    if entry.path in seen:
                        files.append(entry)
                    else:
                        seen.add(entry.path)

            for entry in files:
                try:
                    await _import_file(entry.path)
                    seen.discard(entry.path)
                except Exception as e:
                    await log.awarning("watcher_import_error", file=entry.name, error=str(e)[:80])

        except Exception as e:
            await log.awarning("watcher_error", error=str(e)[:80])

        await asyncio.sleep(10)  # Poll every 10 seconds


async def _import_file(file_path: str) -> None:
    """Import a single file from the incoming folder."""
    import shutil
    from uuid import uuid4

    from brainycat.db import execute
    from brainycat.epub_fix import fix_epub
    from brainycat.extract import extract_metadata
    from brainycat.storage import book_dir

    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()

    book_id = uuid4()
    bdir = book_dir(str(book_id))
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, filename)

    shutil.move(file_path, dst)
    size = os.path.getsize(dst)

    # Fix EPUB
    if ext == ".epub":
        fix_epub(dst)

    # Extract metadata
    meta = extract_metadata(dst)
    title = meta.get("title") or os.path.splitext(filename)[0]

    # Save cover
    cover_path = None
    if meta.get("cover_data"):
        cover_path = os.path.join(bdir, "cover.jpg")
        with open(cover_path, "wb") as f:
            f.write(meta["cover_data"])

    await execute(
        "INSERT INTO books (id, title, cover_path, created_at, updated_at) "
        "VALUES ($1, $2, $3, now(), now())",
        book_id,
        title,
        cover_path,
    )

    # Store language via M:N table
    lang = meta.get("language")
    if lang:
        await execute("INSERT INTO languages (code) VALUES ($1) ON CONFLICT DO NOTHING", lang)
        from brainycat.db import fetch_one as _fo
        lang_row = await _fo("SELECT id FROM languages WHERE code = $1", lang)
        if lang_row:
            await execute("INSERT INTO books_languages (book_id, language_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", book_id, lang_row["id"])
    await execute(
        "INSERT INTO book_files (book_id, file_path, format, file_size, file_name) VALUES ($1, $2, $3, $4, $5)",
        book_id,
        dst,
        ext.lstrip("."),
        size,
        filename,
    )

    # Record filename history if title differs from original filename
    canonical_name = f"{title}{ext}"
    if canonical_name != filename:
        from brainycat.filename_history import record_rename
        await record_rename(book_id, "ingest", filename, canonical_name)

    # Link authors if found
    authors = meta.get("authors") or ([meta["author"]] if meta.get("author") else [])
    for author in authors:
        if not author or not author.strip():
            continue
        from brainycat.db import fetch_one

        row = await fetch_one(
            "INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = $1 RETURNING id",
            author.strip(),
        )
        if row:
            await execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", book_id, row["id"])

    await log.ainfo("watcher_imported", title=title[:50], format=ext)

    # Apply consumption rules
    try:
        from brainycat.consumption_rules import apply_rules
        await apply_rules(str(book_id), filename, title=title)
    except Exception:
        pass

    # Pre-enrichment content guard: detect language and genre from samples
    try:
        from brainycat.content_guard import detect_content_signals
        await detect_content_signals(str(book_id))
    except Exception:
        pass
