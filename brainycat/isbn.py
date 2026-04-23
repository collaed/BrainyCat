"""ISBN & publication metadata extraction — multilingual, front/back matter aware."""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one

ISBN13_RE = re.compile(r"(?:ISBN[-:\s]*)?97[89][\d\s-]{10,17}")
ISBN10_RE = re.compile(r"(?:ISBN[-:\s]*)?\d[-\s]?\d{2}[-\s]?\d{4,6}[-\s]?\d[-\s]?[\dXx]")

# Multilingual anchor patterns for metadata extraction
PUBLISHER_ANCHORS = re.compile(
    r"(?:Published by|Publisher|Éditeur|Publié par|Verlag|Herausgegeben von|Editorial|Publicado por"
    r"|Editore|Casa editrice|Editora|Editura|Förlag|Utgiven av|出版社|出版)\s*:?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
PRINTER_ANCHORS = re.compile(
    r"(?:Printed by|Manufactured in|Achevé d'imprimer|Imprimé par|Gedruckt bei|Druck:"
    r"|Impreso en|Imprenta|Stampato da|Finito di stampare|Impresso por|Tipografia"
    r"|Tipărit la|Tryckt av|印刷|印制)\s*:?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
EDITION_ANCHORS = re.compile(
    r"(?:First|Second|Third|\d+(?:st|nd|rd|th))?\s*(?:Edition|Printing|Édition|Tirage|Auflage|Ausgabe"
    r"|Edición|Reimpresión|Edizione|Ristampa|Edição|Tiragem|Ediția|Utgåva|Upplaga|版次|印次)",
    re.IGNORECASE,
)
TRANSLATOR_ANCHORS = re.compile(
    r"(?:Translated by|Trans\.|Traduit par|Traduction|Übersetzt von|Übersetzung"
    r"|Traducido por|Traducción|Traduzione di|Tradotto da|Traduzido por|Tradução"
    r"|Traducere de|Tradus de|Översatt av|翻译|译者)\s*:?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
COPYRIGHT_RE = re.compile(r"[©Ⓒ]\s*(\d{4})")
DEPOT_LEGAL_RE = re.compile(r"[Dd]épôt\s+légal\s*:?\s*(.+?)(?:\n|$)")
IMPRESSUM_RE = re.compile(r"Impressum|Auflage\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE)
# Number line: "10 9 8 7 6 5 4 3 2 1" — lowest = printing number
NUMBER_LINE_RE = re.compile(r"(?:^|\n)\s*((?:\d+\s+){3,}\d+)\s*(?:\n|$)")


def _clean_isbn(raw: str) -> str | None:
    """Clean and validate ISBN with checksum verification.
    Rejects ASINs (Amazon IDs starting with B) and other non-ISBN identifiers."""
    digits = re.sub(r"[^0-9Xx]", "", raw)

    # Reject ASINs (Amazon IDs: start with B, 10 chars alphanumeric)
    if raw.strip().startswith("B") and len(raw.strip()) == 10:
        return None

    # Reject repeating digits (1111111111, 0000000000)
    if len(set(digits.replace("X", "x"))) <= 2:
        return None

    if len(digits) == 13 and digits.startswith(("978", "979")):
        if _verify_isbn13(digits):
            return digits
    elif len(digits) == 10 and _verify_isbn10(digits):
        return digits
    return None


def _verify_isbn13(isbn: str) -> bool:
    """Verify ISBN-13 checksum."""
    try:
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn[:12]))
        check = (10 - total % 10) % 10
        return check == int(isbn[12])
    except (ValueError, IndexError):
        return False


def _verify_isbn10(isbn: str) -> bool:
    """Verify ISBN-10 checksum."""
    try:
        total = 0
        for i, ch in enumerate(isbn[:9]):
            total += int(ch) * (10 - i)
        check = (11 - total % 11) % 11
        last = 10 if isbn[9] in ("X", "x") else int(isbn[9])
        return check == last
    except (ValueError, IndexError):
        return False


def extract_from_opf(epub_path: str) -> dict[str, Any]:
    """Extract metadata from EPUB's content.opf (Dublin Core)."""
    result: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            opf_path = None
            for name in z.namelist():
                if name.endswith(".opf"):
                    opf_path = name
                    break
            if not opf_path:
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
            for tag, key in [
                ("dc:identifier", "identifiers"),
                ("dc:title", "title"),
                ("dc:creator", "author"),
                ("dc:publisher", "publisher"),
                ("dc:date", "date"),
                ("dc:language", "language"),
            ]:
                matches = re.findall(rf"<{tag}[^>]*>([^<]+)</{tag}>", opf, re.IGNORECASE)
                if matches:
                    result[key] = matches if key == "identifiers" else matches[0].strip()

            for ident in result.get("identifiers", []):
                isbn = _clean_isbn(ident)
                if isbn:
                    result["isbn"] = isbn
                    break
    except Exception:
        pass
    return result


def extract_from_text(text: str) -> dict[str, Any]:
    """Extract ISBN + publication metadata from book text using multilingual anchors."""
    result: dict[str, Any] = {}
    total = len(text)
    if total < 500:
        return result

    # Strategy: front ~10 pages + back ~5 pages (Calibre Extract ISBN style)
    # Estimate ~2000 chars per page
    front = text[:20000]  # ~10 pages
    back = text[-10000:]  # ~5 pages

    # For German books: find Impressum section
    impressum_match = IMPRESSUM_RE.search(text[:5000])
    impressum_section = ""
    if impressum_match:
        start = max(0, impressum_match.start() - 200)
        impressum_section = text[start : start + 2000]

    # For French books: find Achevé d'imprimer (usually last pages)
    acheve_section = ""
    acheve_match = re.search(r"Achevé d'imprimer", text[int(total * 0.90) :], re.IGNORECASE)
    if acheve_match:
        pos = int(total * 0.90) + acheve_match.start()
        acheve_section = text[max(0, pos - 200) : pos + 1000]

    # Combine all search zones
    search_zones = front + "\n" + back + "\n" + impressum_section + "\n" + acheve_section

    # Find all ISBN-like sequences near "ISBN" anchors, prefer 13 over 10
    isbn_anchor_re = re.compile(r"ISBN[-:\s]*(\d[\d\s-]{9,20}[\dXx])", re.IGNORECASE)
    for m in isbn_anchor_re.finditer(search_zones):
        raw = m.group(1)
        digits = re.sub(r"[^0-9Xx]", "", raw)
        # Try ISBN-13 first (first 13 digits)
        if len(digits) >= 13:
            isbn = _clean_isbn(digits[:13])
            if isbn:
                result["isbn"] = isbn
                break
        # Then ISBN-10 (first 10 digits)
        if "isbn" not in result and len(digits) >= 10:
            isbn = _clean_isbn(digits[:10])
            if isbn:
                result["isbn_10"] = isbn
                break

    # Fallback: regex scan without anchor
    if "isbn" not in result and "isbn_10" not in result:
        for m in ISBN13_RE.finditer(search_zones):
            isbn = _clean_isbn(m.group())
            if isbn:
                result["isbn"] = isbn
                break

    if "isbn" not in result and "isbn_10" not in result:
        for m in ISBN10_RE.finditer(search_zones):
            isbn = _clean_isbn(m.group())
            if isbn:
                result["isbn_10"] = isbn
                break

    # Copyright year
    m = COPYRIGHT_RE.search(search_zones)
    if m:
        result["copyright_year"] = m.group(1)

    # Publisher
    m = PUBLISHER_ANCHORS.search(search_zones)
    if m:
        result["publisher"] = m.group(1).strip()[:100]

    # Printer
    m = PRINTER_ANCHORS.search(search_zones)
    if m:
        result["printer"] = m.group(1).strip()[:100]

    # Edition
    m = EDITION_ANCHORS.search(search_zones)
    if m:
        result["edition"] = m.group().strip()

    # Translator
    m = TRANSLATOR_ANCHORS.search(search_zones)
    if m:
        result["translator"] = m.group(1).strip()[:100]

    # Dépôt légal
    m = DEPOT_LEGAL_RE.search(search_zones)
    if m:
        result["depot_legal"] = m.group(1).strip()

    # Number line (printing number)
    m = NUMBER_LINE_RE.search(search_zones)
    if m:
        nums = [int(x) for x in m.group(1).split()]
        if nums == sorted(nums, reverse=True) and len(nums) >= 3:
            result["printing_number"] = min(nums)

    return result


async def extract_and_store_isbn(book_id: str) -> dict[str, Any]:
    """Extract ISBN + metadata from a book's files and update the DB."""
    # Try EPUB/PDF first, then any format via ebook-convert
    row = await fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf WHERE bf.book_id = $1 ORDER BY CASE bf.format WHEN 'epub' THEN 1 WHEN 'pdf' THEN 2 ELSE 3 END LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"ok": False}

    isbn = None
    extra: dict[str, Any] = {}

    # Phase 1: OPF metadata
    if row["format"] == "epub":
        opf_data = extract_from_opf(row["file_path"])
        isbn = opf_data.get("isbn")
        extra.update({k: v for k, v in opf_data.items() if k != "identifiers"})

    # Phase 2: Text content with multilingual anchors
    if not isbn:
        from brainycat.fingerprints import _extract_full_text

        text = ""
        if row["format"] in ("epub", "pdf"):
            text = _extract_full_text(row["file_path"], row["format"])
        elif shutil.which("ebook-convert"):
            # Use ebook-convert for MOBI, AZW3, KFX, etc.
            import asyncio
            import tempfile

            tmp = tempfile.mktemp(suffix=".txt")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ebook-convert",
                    row["file_path"],
                    tmp,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if os.path.isfile(tmp):
                    with open(tmp) as f:
                        text = f.read()
            finally:
                if os.path.isfile(tmp):
                    os.unlink(tmp)

        if text:
            text_data = extract_from_text(text)
            isbn = text_data.get("isbn") or text_data.get("isbn_10")
            extra.update(text_data)

    # If no ISBN found, check if any extracted value is an ASIN
    if not isbn and extra.get("isbn_10"):
        asin = _extract_asin(extra["isbn_10"])
        if asin:
            await execute(
                "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{asin}', $1::jsonb) WHERE id = $2",
                f'"{asin}"',
                UUID(book_id),
            )
            # Try Amazon enrichment with the ASIN
            try:
                from brainycat.sources.amazon import search

                amazon_data = await search(isbn=asin)
                if amazon_data and amazon_data.get("isbn"):
                    isbn = amazon_data["isbn"]  # Got real ISBN from Amazon via ASIN
            except Exception:
                pass

    if isbn:
        current = await fetch_one("SELECT isbn FROM books WHERE id = $1", UUID(book_id))
        if not current or not current["isbn"] or current["isbn"] in ("", "null"):
            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
            await execute(
                "INSERT INTO enrichment_log (book_id, method, success) VALUES ($1, 'isbn_extract', true)",
                UUID(book_id),
            )

    # Store publisher if found and not already set
    if extra.get("publisher"):
        import json

        await execute(
            "UPDATE books SET extra_metadata = extra_metadata || $1::jsonb WHERE id = $2",
            json.dumps(
                {
                    "publisher": extra["publisher"],
                    "printer": extra.get("printer"),
                    "edition": extra.get("edition"),
                    "translator": extra.get("translator"),
                }
            ),
            UUID(book_id),
        )

    return {"ok": True, "isbn": isbn, **extra}


async def batch_extract_isbns(limit: int = 50) -> dict[str, Any]:
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


def _extract_asin(raw: str) -> str | None:
    """Extract ASIN from a string that looks like an Amazon ID."""
    stripped = re.sub(r"[^A-Z0-9]", "", raw.upper().strip())
    if stripped.startswith("B") and len(stripped) == 10 and stripped.isalnum():
        return stripped
    return None


# ISBN Registration Group → Country/Region → Best metadata sources
ISBN_GROUPS: dict[str, dict[str, Any]] = {
    "978-0": {
        "region": "English-speaking",
        "countries": ["US", "UK", "AU", "CA", "NZ"],
        "best_sources": ["google_books", "amazon", "fantastic_fiction", "open_library"],
    },
    "978-1": {
        "region": "English-speaking",
        "countries": ["US", "UK", "AU", "CA", "ZA"],
        "best_sources": ["google_books", "amazon", "fantastic_fiction", "open_library"],
    },
    "978-2": {"region": "French-speaking", "countries": ["FR", "BE", "CH", "CA-QC"], "best_sources": ["babelio", "google_books", "amazon"]},
    "978-3": {"region": "German-speaking", "countries": ["DE", "AT", "CH"], "best_sources": ["dnb", "thalia", "google_books", "amazon"]},
    "978-4": {"region": "Japan", "countries": ["JP"], "best_sources": ["rakuten", "google_books", "amazon"]},
    "978-5": {"region": "Russian-speaking", "countries": ["RU", "BY", "KZ"], "best_sources": ["google_books"]},
    "978-7": {"region": "China", "countries": ["CN"], "best_sources": ["douban", "google_books"]},
    "978-80": {"region": "Czech/Slovak", "countries": ["CZ", "SK"], "best_sources": ["google_books"]},
    "978-82": {"region": "Norway", "countries": ["NO"], "best_sources": ["google_books"]},
    "978-83": {"region": "Poland", "countries": ["PL"], "best_sources": ["google_books"]},
    "978-84": {"region": "Spain", "countries": ["ES"], "best_sources": ["casa_del_libro", "google_books", "amazon"]},
    "978-85": {"region": "Brazil", "countries": ["BR"], "best_sources": ["skoob", "google_books"]},
    "978-87": {"region": "Denmark", "countries": ["DK"], "best_sources": ["google_books"]},
    "978-88": {"region": "Italy", "countries": ["IT"], "best_sources": ["google_books", "amazon"]},
    "978-89": {"region": "South Korea", "countries": ["KR"], "best_sources": ["google_books"]},
    "978-90": {"region": "Netherlands/Belgium", "countries": ["NL", "BE"], "best_sources": ["bol_nl", "google_books"]},
    "978-91": {"region": "Sweden", "countries": ["SE"], "best_sources": ["google_books"]},
    "978-92": {"region": "International orgs", "countries": ["UN", "EU", "UNESCO"], "best_sources": ["google_books", "open_library"]},
    "978-93": {"region": "India", "countries": ["IN"], "best_sources": ["google_books", "amazon"]},
    "978-950": {"region": "Argentina", "countries": ["AR"], "best_sources": ["google_books"]},
    "978-956": {"region": "Chile", "countries": ["CL"], "best_sources": ["google_books"]},
    "978-958": {"region": "Colombia", "countries": ["CO"], "best_sources": ["google_books"]},
    "978-960": {"region": "Greece", "countries": ["GR"], "best_sources": ["google_books"]},
    "978-961": {"region": "Slovenia", "countries": ["SI"], "best_sources": ["google_books"]},
    "978-962": {"region": "Hong Kong", "countries": ["HK"], "best_sources": ["google_books"]},
    "978-963": {"region": "Hungary", "countries": ["HU"], "best_sources": ["google_books"]},
    "978-964": {"region": "Iran", "countries": ["IR"], "best_sources": ["google_books"]},
    "978-965": {"region": "Israel", "countries": ["IL"], "best_sources": ["google_books"]},
    "978-966": {"region": "Ukraine", "countries": ["UA"], "best_sources": ["google_books"]},
    "978-972": {"region": "Portugal", "countries": ["PT"], "best_sources": ["google_books"]},
    "978-973": {"region": "Romania", "countries": ["RO"], "best_sources": ["google_books"]},
    "978-975": {"region": "Turkey", "countries": ["TR"], "best_sources": ["google_books"]},
    "979-10": {"region": "France", "countries": ["FR"], "best_sources": ["babelio", "google_books"]},
    "979-11": {"region": "South Korea", "countries": ["KR"], "best_sources": ["google_books"]},
    "979-12": {"region": "Italy", "countries": ["IT"], "best_sources": ["google_books"]},
}


def isbn_to_region(isbn: str) -> dict[str, Any] | None:
    """Detect country/region from ISBN prefix using isbnlib + our source mapping."""
    if not isbn or len(isbn) < 10:
        return None
    try:
        import isbnlib

        info = isbnlib.info(isbn)  # Offline — no API call
        masked = isbnlib.mask(isbn)  # e.g. "978-2-7417-0468-3"
        # Extract publisher from masked form
        parts = masked.split("-") if masked else []
        publisher_prefix = f"{parts[0]}-{parts[1]}-{parts[2]}" if len(parts) >= 3 else None
    except Exception:
        info = None
        masked = None
        publisher_prefix = None

    # Match against our source mapping
    for prefix in sorted(ISBN_GROUPS.keys(), key=len, reverse=True):
        flat = prefix.replace("-", "")
        if isbn.startswith(flat):
            result = dict(ISBN_GROUPS[prefix])
            if info:
                result["language_info"] = info
            if masked:
                result["masked"] = masked
            if publisher_prefix:
                result["publisher_prefix"] = publisher_prefix
            return result

    # Fallback: isbnlib info only
    if info:
        return {"region": info, "countries": [], "best_sources": ["google_books"], "language_info": info, "masked": masked}
    return None
