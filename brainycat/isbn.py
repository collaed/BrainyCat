"""ISBN extraction — from OPF metadata, text content, and front/back matter."""

from __future__ import annotations

import os
import re
import zipfile
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one

# ISBN-13 pattern: 978 or 979 followed by 10 digits (with optional hyphens)
ISBN13_RE = re.compile(r"(?:ISBN[-:\s]*)?(?:97[89])[-\s]?\d[-\s]?\d{2}[-\s]?\d{4,6}[-\s]?\d{1,3}[-\s]?\d")
ISBN10_RE = re.compile(r"(?:ISBN[-:\s]*)?\d[-\s]?\d{2}[-\s]?\d{4,6}[-\s]?\d[-\s]?[\dXx]")
COPYRIGHT_RE = re.compile(r"©\s*(\d{4})")
PRINTER_RE = re.compile(r"(?:Imprimé par|Achevé d'imprimer|Druck:|Printed by|Printed in)\s+(.+?)(?:\n|$)", re.IGNORECASE)


def _clean_isbn(raw: str) -> str | None:
    """Normalize an ISBN string to digits only."""
    digits = re.sub(r"[^0-9Xx]", "", raw)
    if len(digits) == 13 and digits.startswith(("978", "979")):
        return digits
    if len(digits) == 10:
        return digits
    return None


def extract_from_opf(epub_path: str) -> dict[str, Any]:
    """Extract metadata from EPUB's content.opf (Dublin Core)."""
    result: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            # Find the OPF file
            opf_path = None
            for name in z.namelist():
                if name.endswith(".opf"):
                    opf_path = name
                    break
            if not opf_path:
                # Check container.xml
                try:
                    container = z.read("META-INF/container.xml").decode(errors="replace")
                    m = re.search(r'full-path="([^"]+\.opf)"', container)
                    if m:
                        opf_path = m.group(1)
                except KeyError:
                    pass

            if not opf_path:
                return result

            opf = z.read(opf_path).decode(errors="replace")

            # Extract Dublin Core fields
            for tag, key in [
                ("dc:identifier", "identifiers"),
                ("dc:title", "title"),
                ("dc:creator", "author"),
                ("dc:publisher", "publisher"),
                ("dc:date", "date"),
                ("dc:language", "language"),
                ("dc:description", "description"),
            ]:
                matches = re.findall(rf"<{tag}[^>]*>([^<]+)</{tag}>", opf, re.IGNORECASE)
                if matches:
                    if key == "identifiers":
                        result[key] = matches
                    else:
                        result[key] = matches[0].strip()

            # Extract ISBN from identifiers
            for ident in result.get("identifiers", []):
                isbn = _clean_isbn(ident)
                if isbn:
                    result["isbn"] = isbn
                    break
    except Exception:
        pass
    return result


def extract_isbn_from_text(text: str) -> dict[str, Any]:
    """Extract ISBN, copyright year, and printer from book text."""
    result: dict[str, Any] = {}

    # Search front matter (first 10%) and back matter (last 10%)
    front = text[: int(len(text) * 0.1)]
    back = text[int(len(text) * 0.9) :]
    search_text = front + "\n" + back

    # ISBN-13
    for m in ISBN13_RE.finditer(search_text):
        isbn = _clean_isbn(m.group())
        if isbn:
            result["isbn"] = isbn
            break

    # ISBN-10 fallback
    if "isbn" not in result:
        for m in ISBN10_RE.finditer(search_text):
            isbn = _clean_isbn(m.group())
            if isbn:
                result["isbn_10"] = isbn
                break

    # Copyright year
    m = COPYRIGHT_RE.search(search_text)
    if m:
        result["copyright_year"] = m.group(1)

    # Printer (EU legal requirement)
    m = PRINTER_RE.search(search_text)
    if m:
        result["printer"] = m.group(1).strip()

    return result


async def extract_and_store_isbn(book_id: str) -> dict[str, Any]:
    """Extract ISBN from a book's files and update the DB."""
    row = await fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf WHERE bf.book_id = $1 AND bf.format IN ('epub','pdf') LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"ok": False}

    isbn = None
    extra: dict[str, Any] = {}

    # Phase 1: OPF metadata (most reliable)
    if row["format"] == "epub":
        opf_data = extract_from_opf(row["file_path"])
        isbn = opf_data.get("isbn")
        extra.update({k: v for k, v in opf_data.items() if k != "identifiers"})

    # Phase 2: Text content (front/back matter)
    if not isbn:
        from brainycat.fingerprints import _extract_full_text

        text = _extract_full_text(row["file_path"], row["format"])
        if text:
            text_data = extract_isbn_from_text(text)
            isbn = text_data.get("isbn") or text_data.get("isbn_10")
            extra.update(text_data)

    if isbn:
        current = await fetch_one("SELECT isbn FROM books WHERE id = $1", UUID(book_id))
        if not current or not current["isbn"] or current["isbn"] in ("", "null"):
            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
            await execute(
                "INSERT INTO enrichment_log (book_id, method, success) VALUES ($1, 'isbn_extract', true)",
                UUID(book_id),
            )

    return {"ok": True, "isbn": isbn, **extra}


async def batch_extract_isbns(limit: int = 50) -> dict[str, Any]:
    """Extract ISBNs for books that don't have one."""
    rows = await fetch_all(
        """
        SELECT b.id FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        WHERE (b.isbn IS NULL OR b.isbn = '') AND bf.format IN ('epub','pdf')
        LIMIT $1
    """,
        limit,
    )

    found = 0
    for r in rows:
        result = await extract_and_store_isbn(str(r["id"]))
        if result.get("isbn"):
            found += 1

    total_missing = await fetch_one("SELECT count(*) as n FROM books WHERE isbn IS NULL OR isbn = ''")
    return {"extracted": found, "batch": len(rows), "still_missing": total_missing["n"] if total_missing else 0}
