"""Smart PDF→EPUB3 conversion — AI-powered structure extraction.

Fallback chain:
1. pdf-craft (book-focused, outputs EPUB directly, GPU optional)
2. Docling (IBM, structure extraction → proper EPUB3 with chapters/images/TOC)
3. ebook-convert (Calibre heuristics, always available)
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import Any


async def pdf_to_epub3(pdf_path: str, output_path: str | None = None) -> dict[str, Any]:
    """Convert PDF to EPUB3 using the best available tool."""
    if not os.path.isfile(pdf_path):
        return {"error": "file not found"}

    out = output_path or pdf_path.rsplit(".", 1)[0] + ".epub"

    result = await _try_pdfcraft(pdf_path, out)
    if result.get("ok"):
        return result

    result = await _try_docling(pdf_path, out)
    if result.get("ok"):
        return result

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
        return {"error": f"pdf-craft: {str(e)[:100]}"}
    return {}


async def _try_docling(pdf_path: str, out_path: str) -> dict[str, Any]:
    """Docling (IBM): AI structure extraction → proper EPUB3."""
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        doc = result.document

        # Extract metadata
        title = os.path.basename(pdf_path).rsplit(".", 1)[0]
        if hasattr(doc, "title") and doc.title:
            title = doc.title

        # Export to markdown and split into chapters
        md = doc.export_to_markdown()
        chapters = _split_chapters(md)

        # Extract images if available
        images: dict[str, bytes] = {}
        if hasattr(doc, "pictures"):
            for i, pic in enumerate(doc.pictures):
                if hasattr(pic, "image") and pic.image:
                    img_name = f"image_{i}.png"
                    images[img_name] = pic.image.tobytes() if hasattr(pic.image, "tobytes") else bytes(pic.image)

        # Build proper EPUB3
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier(f"brainycat-docling-{hash(pdf_path)}")
        book.set_title(title)
        book.set_language("en")

        # Add images
        for img_name, img_data in images.items():
            img_item = epub.EpubItem(file_name=f"images/{img_name}", media_type="image/png", content=img_data)
            book.add_item(img_item)

        # Add chapters
        spine: list[Any] = ["nav"]
        toc: list[Any] = []
        for i, (ch_title, ch_md) in enumerate(chapters):
            html = _markdown_to_html(ch_md, images)
            ch = epub.EpubHtml(title=ch_title, file_name=f"ch_{i:03d}.xhtml", lang="en")
            ch.set_content(
                f'<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{ch_title}</title></head><body>\n<h1>{ch_title}</h1>\n{html}\n</body></html>'
            )
            book.add_item(ch)
            spine.append(ch)
            toc.append(epub.Link(f"ch_{i:03d}.xhtml", ch_title, f"ch_{i}"))

        book.toc = toc
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = spine

        epub.write_epub(out_path, book)
        if os.path.isfile(out_path):
            return {"ok": True, "method": "docling", "path": out_path, "chapters": len(chapters), "images": len(images)}
    except ImportError:
        pass
    except Exception as e:
        return {"error": f"docling: {str(e)[:100]}"}
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


def _split_chapters(md: str) -> list[tuple[str, str]]:
    """Split markdown into chapters at # headings."""
    chapters: list[tuple[str, str]] = []
    current_title = "Introduction"
    current_content: list[str] = []

    for line in md.split("\n"):
        if line.startswith("# ") and not line.startswith("##"):
            if current_content:
                chapters.append((current_title, "\n".join(current_content)))
            current_title = line[2:].strip()
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        chapters.append((current_title, "\n".join(current_content)))

    # If no chapters found, treat whole document as one
    if not chapters:
        chapters = [("Content", md)]

    return chapters


def _markdown_to_html(md: str, images: dict[str, bytes] | None = None) -> str:
    """Convert markdown to XHTML with proper structure."""
    html = md

    # Tables: detect and convert
    html = re.sub(r"\|(.+)\|\n\|[-| ]+\|\n((?:\|.+\|\n)*)", _convert_table, html)

    # Headings
    html = re.sub(r"^###### (.+)$", r"<h6>\1</h6>", html, flags=re.MULTILINE)
    html = re.sub(r"^##### (.+)$", r"<h5>\1</h5>", html, flags=re.MULTILINE)
    html = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)

    # Bold/italic
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    # Lists
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>\n?)+", lambda m: f"<ul>\n{m.group()}</ul>\n", html)
    html = re.sub(r"^\d+\. (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

    # Images
    html = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<figure><img src="\2" alt="\1"/><figcaption>\1</figcaption></figure>', html)

    # Footnotes (basic)
    html = re.sub(r"\[\^(\d+)\]", r'<sup><a href="#fn\1" epub:type="noteref">\1</a></sup>', html)

    # Paragraphs: wrap remaining text blocks
    lines = html.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append("")
        elif stripped.startswith("<"):
            result.append(stripped)
        else:
            result.append(f"<p>{stripped}</p>")

    return "\n".join(result)


def _convert_table(match: re.Match) -> str:
    """Convert markdown table to HTML table."""
    header = match.group(1)
    rows = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
    cells = [c.strip() for c in header.split("|") if c.strip()]
    html = "<table>\n<thead><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr></thead>\n<tbody>\n"
    for row in rows.strip().split("\n"):
        if row.strip():
            rcells = [c.strip() for c in row.split("|") if c.strip()]
            html += "<tr>" + "".join(f"<td>{c}</td>" for c in rcells) + "</tr>\n"
    html += "</tbody></table>\n"
    return html


def available_converters() -> dict[str, bool]:
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
