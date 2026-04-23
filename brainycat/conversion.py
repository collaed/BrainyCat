"""Unified conversion service — THE single entry point for all format conversions.

Replaces: convert.py, format_convert.py, pdf_convert.py conversion logic.
Those modules still exist for backward compat but should delegate here.

Handles: styling profiles, ebook-convert flags, PDF AI chain, WeasyPrint.
One CSS file, three conversion paths, consistent output.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import tempfile
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one

STYLES_DIR = pathlib.Path(__file__).parent.parent / "static" / "epub-styles"

PROFILES = {
    "classic": {"css_file": "classic.css", "justify": True, "font": "Georgia"},
    "modern": {"css_file": "modern.css", "justify": False, "font": "Helvetica"},
    "academic": {"css_file": "academic.css", "justify": True, "font": "Times New Roman"},
}


def _load_css(profile: str = "classic") -> str:
    p = PROFILES.get(profile, PROFILES["classic"])
    css_path = STYLES_DIR / p["css_file"]
    if css_path.is_file():
        return css_path.read_text()
    return ""


async def convert(
    src: str,
    dest: str,
    profile: str = "classic",
    extra_css: str | None = None,
) -> dict[str, Any]:
    """Single entry point for ALL conversions."""
    if not os.path.isfile(src):
        return {"error": "source file not found"}

    css = _load_css(profile)
    if extra_css:
        css += "\n" + extra_css

    src_ext = os.path.splitext(src)[1].lower()
    dest_ext = os.path.splitext(dest)[1].lower()

    # PDF → EPUB: use AI chain
    if src_ext == ".pdf" and dest_ext == ".epub":
        return await _pdf_to_epub(src, dest, css)

    # Any → Any via ebook-convert (with styling)
    if shutil.which("ebook-convert"):
        return await _ebook_convert(src, dest, css)

    # EPUB → PDF via WeasyPrint
    if dest_ext == ".pdf" and src_ext == ".epub":
        return await _weasyprint(src, dest, css)

    return {"error": f"no converter for {src_ext}→{dest_ext}"}


async def _ebook_convert(src: str, dest: str, css: str) -> dict[str, Any]:
    """Calibre ebook-convert with proper styling flags."""
    css_path = tempfile.mktemp(suffix=".css")
    with open(css_path, "w") as css_file:
        css_file.write(css)

    cmd = [
        "ebook-convert",
        src,
        dest,
        "--extra-css",
        css_path,
        "--change-justification",
        "justify",
        "--insert-metadata",
        "--chapter",
        "//*[name()='h1' or name()='h2']",
        "--page-breaks-before",
        "//*[name()='h1']",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0 and os.path.isfile(dest):
            return {"ok": True, "method": "ebook-convert", "path": dest}
        return {"error": "ebook-convert failed"}
    finally:
        os.unlink(css_path)


async def _pdf_to_epub(src: str, dest: str, css: str) -> dict[str, Any]:
    """PDF → EPUB3 via AI fallback chain."""
    # Try pdf-craft first
    try:
        from pdf_craft import PDFCraft

        craft = PDFCraft()
        craft.pdf_to_epub(src, dest)
        if os.path.isfile(dest):
            return {"ok": True, "method": "pdf-craft", "path": dest}
    except (ImportError, Exception):
        pass

    # Fallback to ebook-convert
    return await _ebook_convert(src, dest, css)


async def _weasyprint(src: str, dest: str, css: str) -> dict[str, Any]:
    """EPUB → PDF via WeasyPrint."""
    try:
        # Extract HTML from EPUB
        import ebooklib
        from ebooklib import epub
        from weasyprint import HTML

        book = epub.read_epub(src, options={"ignore_ncx": True})
        html_parts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            html_parts.append(item.get_content().decode("utf-8", errors="replace"))

        full_html = f"<html><head><style>{css}</style></head><body>{''.join(html_parts)}</body></html>"
        HTML(string=full_html).write_pdf(dest)
        if os.path.isfile(dest):
            return {"ok": True, "method": "weasyprint", "path": dest}
    except Exception as e:
        return {"error": f"weasyprint: {str(e)[:100]}"}
    return {"error": "weasyprint failed"}


async def convert_book(book_id: str, target_format: str, profile: str = "classic") -> dict[str, Any]:
    """Convert a book to target format, register the output file."""
    row = await fetch_one(
        """
        SELECT bf.file_path, bf.format FROM book_files bf
        WHERE bf.book_id = $1 AND bf.format IN ('epub','pdf','mobi','azw3','txt','docx')
        ORDER BY CASE bf.format WHEN 'epub' THEN 1 WHEN 'pdf' THEN 2 ELSE 3 END
        LIMIT 1
    """,
        UUID(book_id),
    )
    if not row:
        return {"error": "no convertible file"}

    dest = f"/data/books/{book_id}.{target_format}"
    result = await convert(row["file_path"], dest, profile)

    if result.get("ok"):
        existing = await fetch_one(
            "SELECT id FROM book_files WHERE book_id=$1 AND format=$2",
            UUID(book_id),
            target_format,
        )
        if not existing:
            await execute(
                "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,$3,$4,$5)",
                uuid4(),
                UUID(book_id),
                target_format,
                dest,
                os.path.basename(dest),
            )

    return result
