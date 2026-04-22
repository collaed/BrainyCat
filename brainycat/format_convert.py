"""Format conversion — EPUB→PDF, EPUB→MOBI, EPUB→AZW3.

Uses:
1. WeasyPrint for EPUB→PDF (already working)
2. Calibre's ebook-convert if available (all formats)
3. KindleGen for EPUB→MOBI/AZW3 (Amazon's tool)

Falls back gracefully: tries ebook-convert first, then kindlegen, then WeasyPrint.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one


async def convert_book(book_id: str, target_format: str) -> dict[str, Any]:
    """Convert a book to the target format."""
    row = await fetch_one(
        """
        SELECT bf.file_path, bf.format, b.title
        FROM book_files bf JOIN books b ON b.id = bf.book_id
        WHERE bf.book_id = $1 AND bf.format IN ('epub', 'pdf')
        ORDER BY CASE bf.format WHEN 'epub' THEN 1 WHEN 'pdf' THEN 2 END
        LIMIT 1
    """,
        UUID(book_id),
    )
    if not row:
        return {"error": "no convertible source file"}

    src = row["file_path"]
    src_fmt = row["format"]
    out_path = f"/data/books/{book_id}.{target_format}"

    # Try ebook-convert (Calibre) first — handles everything
    if shutil.which("ebook-convert"):
        proc = await asyncio.create_subprocess_exec(
            "ebook-convert",
            src,
            out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _stderr = await proc.communicate()
        if proc.returncode == 0 and os.path.isfile(out_path):
            await _register_file(book_id, target_format, out_path)
            return {"ok": True, "method": "ebook-convert", "path": out_path}

    # Try kindlegen for MOBI/AZW3
    if target_format in ("mobi", "azw3") and src_fmt == "epub":
        kindlegen = shutil.which("kindlegen")
        if kindlegen:
            tmp_out = src.replace(".epub", ".mobi")
            proc = await asyncio.create_subprocess_exec(
                kindlegen,
                src,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if os.path.isfile(tmp_out):
                shutil.move(tmp_out, out_path)
                await _register_file(book_id, target_format, out_path)
                return {"ok": True, "method": "kindlegen", "path": out_path}

    # WeasyPrint for PDF
    if target_format == "pdf" and src_fmt == "epub":
        from brainycat.convert import epub_to_pdf

        result = await epub_to_pdf(book_id)
        if result.get("ok"):
            return {"ok": True, "method": "weasyprint", "path": result.get("path")}

    return {
        "error": f"no converter available for {src_fmt}→{target_format}",
        "hint": "Install ebook-convert (Calibre) for full format support",
    }


async def _register_file(book_id: str, fmt: str, path: str) -> None:
    """Register a converted file in the database."""
    existing = await fetch_one(
        "SELECT id FROM book_files WHERE book_id = $1 AND format = $2",
        UUID(book_id),
        fmt,
    )
    if not existing:
        fname = os.path.basename(path)
        await execute(
            "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,$3,$4,$5)",
            uuid4(),
            UUID(book_id),
            fmt,
            path,
            fname,
        )


async def list_converters() -> dict[str, Any]:
    """List available format converters."""
    return {
        "ebook-convert": shutil.which("ebook-convert") is not None,
        "kindlegen": shutil.which("kindlegen") is not None,
        "weasyprint": True,  # Always available (Python package)
        "supported_conversions": _supported_conversions(),
    }


def _supported_conversions() -> list[str]:
    """List supported conversion paths."""
    paths = ["epub→pdf"]
    if shutil.which("ebook-convert"):
        paths.extend(["epub→mobi", "epub→azw3", "epub→txt", "epub→docx", "pdf→epub", "mobi→epub", "azw3→epub", "txt→epub"])
    elif shutil.which("kindlegen"):
        paths.extend(["epub→mobi"])
    return paths
