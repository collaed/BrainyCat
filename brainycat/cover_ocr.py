"""OCR a book's cover image — a manual "this book is misidentified" fix.

Unlike isbn_from_cover_search() (brainycat/isbn.py), which just re-searches Google Books using the
book's existing, possibly-wrong title, this actually reads the cover image with Tesseract, which is
the only source of truth independent of whatever bad metadata got attached at import.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.isbn import ISBN10_RE, ISBN13_RE, _clean_isbn


def _ocr_image(image_path: str, lang: str = "eng+fra") -> str:
    import pytesseract
    from PIL import Image

    return pytesseract.image_to_string(Image.open(image_path), lang=lang)


def _find_isbn(text: str) -> str | None:
    for pattern in (ISBN13_RE, ISBN10_RE):
        for m in pattern.finditer(text):
            isbn = _clean_isbn(m.group())
            if isbn:
                return isbn
    return None


async def _cover_or_first_page_image(book_id: str, cover_path: str | None) -> str | None:
    """Fall back to rendering a PDF's first page as an image when there's no cover file yet —
    covers the "even start with a PDF's first page" case for books without an extracted cover."""
    if cover_path and os.path.isfile(cover_path):
        return cover_path

    pdf_row = await fetch_one("SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1", UUID(book_id))
    if not pdf_row or not os.path.isfile(pdf_row["file_path"]):
        return None

    import os as _os
    import tempfile

    import fitz

    doc = fitz.open(pdf_row["file_path"])
    if len(doc) == 0:
        doc.close()
        return None
    pix = doc[0].get_pixmap(dpi=300)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    _os.close(fd)  # pix.save() reopens the path itself; we only needed mkstemp for a race-free name
    pix.save(tmp)
    doc.close()
    return tmp


async def _search_by_text(text: str) -> list[dict[str, Any]]:
    """No ISBN on the cover — suggest candidate books via a plain Google Books text search on the
    first substantial OCR'd line (usually the title). Suggestions only: text-derived title matches
    are much lower-confidence than a checksum-valid ISBN, so nothing is auto-applied here."""
    query_line = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 4), None)
    if not query_line:
        return []

    from brainycat.http_client import get_client

    params = {"q": query_line, "maxResults": 5}
    if settings.google_books_api_key:
        params["key"] = settings.google_books_api_key
    try:
        resp = await get_client().get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=10)
    except Exception:
        return []
    if resp.status_code != 200:
        return []

    suggestions = []
    for item in resp.json().get("items", []):
        vi = item.get("volumeInfo", {})
        isbn = next((i["identifier"] for i in vi.get("industryIdentifiers", []) if i["type"] == "ISBN_13"), None)
        suggestions.append({"title": vi.get("title"), "authors": vi.get("authors", []), "isbn": isbn})
    return suggestions


async def ocr_cover(book_id: str) -> dict[str, Any]:
    """OCR the cover (or the PDF's first page, if there's no extracted cover yet). A checksum-valid
    ISBN found on it is trustworthy enough to apply directly and trigger re-enrichment; otherwise,
    suggest candidate books via a text search on the OCR'd title line, for the user to pick from."""
    book = await fetch_one("SELECT cover_path FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return {"error": "not found"}

    image_path = await _cover_or_first_page_image(book_id, book["cover_path"])
    if not image_path:
        return {"error": "no cover image or PDF first page available"}

    try:
        text = _ocr_image(image_path)
    except Exception as e:
        return {"error": f"OCR failed: {e}"}
    finally:
        if image_path != book["cover_path"] and os.path.isfile(image_path):
            os.unlink(image_path)

    text = text.strip()
    if not text:
        return {"ok": True, "text": "", "isbn_found": None, "suggestions": []}

    isbn = _find_isbn(text)
    if isbn:
        await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
        from brainycat.metadata import enrich_book

        enrich_result = await enrich_book(book_id)
        return {"ok": True, "text": text, "isbn_found": isbn, "re_enriched": bool(enrich_result.get("enriched"))}

    suggestions = await _search_by_text(text)
    return {"ok": True, "text": text, "isbn_found": None, "suggestions": suggestions}
