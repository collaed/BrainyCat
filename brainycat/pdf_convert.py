"""Smart PDF→EPUB3 conversion — AI-powered structure extraction.

Fallback chain:
1. pdf-craft (book-focused, outputs EPUB directly, GPU-accelerated)
2. Docling (IBM, best for academic/structured PDFs, outputs Markdown→EPUB)
3. ebook-convert (Calibre, heuristic-based, always available)

pdf-craft and Docling are optional — install with:
  pip install pdf-craft    # Book-focused, GPU optional
  pip install docling      # IBM, ~500MB models

Without them, falls back to ebook-convert (already in Docker).
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any


async def pdf_to_epub3(pdf_path: str, output_path: str | None = None) -> dict[str, Any]:
    """Convert PDF to EPUB3 using the best available tool."""
    if not os.path.isfile(pdf_path):
        return {"error": "file not found"}

    out = output_path or pdf_path.rsplit(".", 1)[0] + ".epub"

    # Try pdf-craft first (book-focused, outputs EPUB directly)
    result = await _try_pdfcraft(pdf_path, out)
    if result.get("ok"):
        return result

    # Try Docling (best structure extraction, needs Markdown→EPUB step)
    result = await _try_docling(pdf_path, out)
    if result.get("ok"):
        return result

    # Fallback: ebook-convert (always available)
    result = await _try_ebook_convert(pdf_path, out)
    if result.get("ok"):
        return result

    return {"error": "no PDF converter available"}


async def _try_pdfcraft(pdf_path: str, out_path: str) -> dict[str, Any]:
    """pdf-craft: book-focused, outputs EPUB directly."""
    try:
        from pdf_craft import PDFCraft

        craft = PDFCraft()
        craft.pdf_to_epub(pdf_path, out_path)
        if os.path.isfile(out_path):
            return {"ok": True, "method": "pdf-craft", "path": out_path}
    except ImportError:
        pass
    except Exception as e:
        return {"error": f"pdf-craft failed: {str(e)[:100]}"}
    return {}


async def _try_docling(pdf_path: str, out_path: str) -> dict[str, Any]:
    """Docling (IBM): AI structure extraction → Markdown → EPUB3."""
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        md = result.document.export_to_markdown()

        # Markdown → EPUB3 via ebooklib
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier("brainycat-docling-convert")
        book.set_title(os.path.basename(pdf_path).rsplit(".", 1)[0])
        book.set_language("en")

        # Convert markdown to HTML (basic)
        import re

        html = md
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"\n\n", "</p><p>", html)
        html = f"<p>{html}</p>"

        chapter = epub.EpubHtml(title="Content", file_name="content.xhtml", lang="en")
        chapter.set_content(f"<html><body>{html}</body></html>")
        book.add_item(chapter)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]
        book.toc = [epub.Link("content.xhtml", "Content", "content")]

        epub.write_epub(out_path, book)
        if os.path.isfile(out_path):
            return {"ok": True, "method": "docling", "path": out_path}
    except ImportError:
        pass
    except Exception as e:
        return {"error": f"docling failed: {str(e)[:100]}"}
    return {}


async def _try_ebook_convert(pdf_path: str, out_path: str) -> dict[str, Any]:
    """Calibre ebook-convert: heuristic-based, always available."""
    if not shutil.which("ebook-convert"):
        return {}
    proc = await asyncio.create_subprocess_exec(
        "ebook-convert",
        pdf_path,
        out_path,
        "--no-default-epub-cover",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0 and os.path.isfile(out_path):
        return {"ok": True, "method": "ebook-convert", "path": out_path}
    return {"error": "ebook-convert failed"}


def available_converters() -> dict[str, bool]:
    """Check which PDF→EPUB converters are available."""
    result = {"ebook-convert": shutil.which("ebook-convert") is not None}
    try:
        import pdf_craft  # noqa: F401

        result["pdf-craft"] = True
    except ImportError:
        result["pdf-craft"] = False
    try:
        import docling  # noqa: F401

        result["docling"] = True
    except ImportError:
        result["docling"] = False
    return result
