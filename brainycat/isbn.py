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
    r"(\d+(?:st|nd|rd|th|re|e|ère|ème|te|\.)?)\s*(?:Edition|Printing|Édition|Tirage|Auflage|Ausgabe"
    r"|Edición|Reimpresión|Edizione|Ristampa|Edição|Tiragem|Ediția|Utgåva|Upplaga|版次|印次)"
    r"|(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth"
    r"|Première|Deuxième|Troisième|Quatrième|Cinquième|Sixième"
    r"|Erste|Zweite|Dritte|Vierte|Fünfte|Sechste)"
    r"\s+(?:Edition|Édition|Auflage|Edición|Edizione|Edição)",
    re.IGNORECASE,
)
TRANSLATOR_ANCHORS = re.compile(
    r"(?:Translated by|Trans\.|Traduit par|Traduction|Übersetzt von|Übersetzung"
    r"|Traducido por|Traducción|Traduzione di|Tradotto da|Traduzido por|Tradução"
    r"|Traducere de|Tradus de|Översatt av|翻译|译者)\s*:?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
COPYRIGHT_RE = re.compile(r"[©Ⓒ]\s*(\d{4})")
DEPOT_LEGAL_RE = re.compile(r"[Dd]épôt\s+légal\s*:?\s*([a-zA-Zéèêëàâùûôîïç\s]+\d{4})")
IMPRESSUM_RE = re.compile(r"Impressum|Auflage\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE)
# Number line: "10 9 8 7 6 5 4 3 2 1" — lowest = printing number
NUMBER_LINE_RE = re.compile(r"(?:^|\n)\s*((?:\d+\s+){3,}\d+)\s*(?:\n|$)")


def _clean_isbn(raw: str) -> str | None:
    """Clean and validate ISBN with checksum verification.
    Rejects ASINs (Amazon IDs starting with B) and other non-ISBN identifiers."""
    digits = re.sub(r"[^0-9Xx]", "", raw.translate({0x2010: "", 0x2011: "", 0x2012: "", 0x2013: "", 0x2014: ""}))

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
    # 12 digits starting with 978/979 — missing check digit (misprint)
    elif len(digits) == 12 and digits.startswith(("978", "979")):
        check = (10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits)) % 10) % 10
        return digits + str(check)
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

    # Full text search — regex on even 1MB text is <50ms, no need to truncate
    search_zones = text

    # Collect ALL ISBNs with context (type detection from surrounding text)
    isbn_context_re = re.compile(
        r"(?P<ctx>[^\n]{0,40})"
        r"ISBN\s*(?P<qual>[^\d:]{0,30}?)\s*:?\s*"
        r"(?P<num>[\d][\d\s\-\u2010\u2011\u2012\u2013\u2014]{9,20}[\dXx])",
        re.IGNORECASE,
    )
    all_isbns: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in isbn_context_re.finditer(search_zones):
        raw = m.group("num")
        ctx = (m.group("ctx") + " " + m.group("qual")).lower()
        digits = re.sub(
            r"[^0-9Xx]",
            "",
            raw.translate({0x2010: "", 0x2011: "", 0x2012: "", 0x2013: "", 0x2014: ""}),
        )
        isbn = None
        if len(digits) >= 13:
            isbn = _clean_isbn(digits[:13])
        if not isbn and len(digits) >= 10:
            isbn = _clean_isbn(digits[:10])
        if not isbn:
            isbn = _clean_isbn(digits)  # try 12-digit completion
        if isbn and isbn not in seen:
            seen.add(isbn)
            # Detect type from context
            isbn_type = "print"
            if any(k in ctx for k in ("numérique", "numeric", "ebook", "e-book", "ebk", "digital", "epub")):
                isbn_type = "ebook"
            elif any(k in ctx for k in ("pdf",)):
                isbn_type = "pdf"
            elif any(k in ctx for k in ("audio", "audiobook", "hörbuch")):
                isbn_type = "audiobook"
            elif any(k in ctx for k in ("pbk", "paperback", "broché", "poche")):
                isbn_type = "paperback"
            elif any(k in ctx for k in ("hbk", "hardcover", "relié", "hardback")):
                isbn_type = "hardcover"
            all_isbns.append({"isbn": isbn, "type": isbn_type})

    # Fallback: regex scan without anchor
    if not all_isbns:
        for m in ISBN13_RE.finditer(search_zones):
            isbn = _clean_isbn(m.group())
            if isbn and isbn not in seen:
                seen.add(isbn)
                all_isbns.append({"isbn": isbn, "type": "unknown"})
                break
    if not all_isbns:
        for m in ISBN10_RE.finditer(search_zones):
            isbn = _clean_isbn(m.group())
            if isbn and isbn not in seen:
                all_isbns.append({"isbn": isbn, "type": "unknown"})
                break

    if all_isbns:
        result["all_isbns"] = all_isbns
        # Primary ISBN: prefer ebook > pdf > print > unknown
        type_priority = {"ebook": 0, "pdf": 1, "unknown": 2, "print": 3, "paperback": 4, "hardcover": 5, "audiobook": 6}
        best = min(all_isbns, key=lambda x: type_priority.get(x["type"], 99))
        if len(best["isbn"]) == 13:
            result["isbn"] = best["isbn"]
        else:
            result["isbn_10"] = best["isbn"]

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

    # Digital production house (Nord Compo, Jouve, etc.)
    prod_re = re.compile(
        r"(?:réalisé par|réalisation|composition|mise en page|numérisation|produced by|typeset by"
        r"|digital production|Herstellung|Satz)\s*:?\s*(.+?)[\.\n]",
        re.IGNORECASE,
    )
    m = prod_re.search(search_zones)
    if m:
        result["digital_production"] = m.group(1).strip()[:100]

    # Original title (for translations)
    orig_re = re.compile(
        r"(?:Titre original|Original title|Originaltitel|Título original)\s*:?\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    )
    m = orig_re.search(search_zones)
    if m:
        result["original_title"] = m.group(1).strip()[:200]

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


async def ocr_last_page_for_isbn(book_id: str) -> dict[str, Any]:
    """Scan PDF last pages or EPUB copyright pages for ISBN."""
    # Try EPUB first — scan copyright/info pages (first 5 spine items)
    epub_row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if epub_row and os.path.isfile(epub_row["file_path"]):
        try:
            import zipfile

            with zipfile.ZipFile(epub_row["file_path"]) as zf:
                htmls = sorted(n for n in zf.namelist() if n.endswith((".xhtml", ".html")))
                for h in htmls[:8]:
                    text = zf.read(h).decode("utf-8", errors="ignore")
                    result = extract_from_text(text)
                    isbn = result.get("isbn") or result.get("isbn_10")
                    if isbn:
                        current = await fetch_one("SELECT isbn FROM books WHERE id = $1", UUID(book_id))
                        if not current or not current["isbn"]:
                            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
                        return {"ok": True, "isbn": isbn, "source": "epub_content"}
        except Exception:
            pass

    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"ok": False, "reason": "no pdf or epub"}

    try:
        import fitz

        doc = fitz.open(row["file_path"])
        num_pages = len(doc)
        if num_pages == 0:
            doc.close()
            return {"ok": False, "reason": "empty pdf"}

        # Extract text from last 2 pages + first 2 pages (copyright page)
        text = ""
        for page_idx in list(range(min(15, num_pages))) + list(range(max(0, num_pages - 3), num_pages)):
            text += doc[page_idx].get_text() + "\n"
        doc.close()

        # If we got text, scan for ISBN
        if len(text.strip()) > 20:
            result = extract_from_text(text)
            isbn = result.get("isbn") or result.get("isbn_10")
            if isbn:
                current = await fetch_one("SELECT isbn FROM books WHERE id = $1", UUID(book_id))
                if not current or not current["isbn"]:
                    await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
                    return {"ok": True, "isbn": isbn, "source": "last_page_text"}

        # No text on last pages — try OCR via Intello on just the last page
        import fitz as _fitz

        doc = _fitz.open(row["file_path"])
        last_page = doc[num_pages - 1]
        # Render last page as image
        pix = last_page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        doc.close()

        # Submit just this image for OCR
        import tempfile

        tmp = tempfile.mktemp(suffix=".png")
        with open(tmp, "wb") as f:
            f.write(img_bytes)

        # Try barcode decoding first (reads EAN-13 ISBN barcodes from images)
        try:
            import io

            from PIL import Image
            from pyzbar.pyzbar import decode

            img = Image.open(io.BytesIO(img_bytes))
            barcodes = decode(img)
            for barcode in barcodes:
                data = barcode.data.decode("utf-8", errors="ignore")
                isbn = _clean_isbn(data)
                if isbn:
                    await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
                    os.unlink(tmp)
                    return {"ok": True, "isbn": isbn, "source": "barcode_scan"}
        except ImportError:
            pass  # pyzbar not installed
        except Exception:
            pass

        # Try Tesseract locally first (faster than Intello for one page)
        import subprocess

        try:
            result = subprocess.run(
                ["tesseract", tmp, "-", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                ocr_text = result.stdout
                isbn_result = extract_from_text(ocr_text)
                isbn = isbn_result.get("isbn") or isbn_result.get("isbn_10")
                if isbn:
                    await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
                    os.unlink(tmp)
                    return {"ok": True, "isbn": isbn, "source": "last_page_ocr"}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        os.unlink(tmp)
        return {"ok": False, "reason": "no isbn found on last pages"}

    except Exception as e:
        return {"ok": False, "reason": str(e)[:100]}


def extract_from_pdf_metadata(pdf_path: str) -> str | None:
    """Extract ISBN from PDF internal metadata (Subject, Keywords, Custom fields).

    PDFs store metadata in two places:
    - DocInfo dict (old-style: /Subject, /Keywords, /Author)
    - XMP metadata (XML-based, richer)
    """
    import fitz

    try:
        doc = fitz.open(pdf_path)
        meta = doc.metadata or {}
        doc.close()

        # Check all metadata fields for ISBN patterns
        for field in ["subject", "keywords", "comments", "author", "title", "producer", "creator"]:
            value = meta.get(field, "") or ""
            if "978" in value or "979" in value or "isbn" in value.lower():
                # Try to extract ISBN from this field
                import re

                matches = re.findall(r"97[89][\d\s-]{10,17}", value)
                for m in matches:
                    cleaned = _clean_isbn(m)
                    if cleaned:
                        return cleaned
    except Exception:
        pass
    return None


def extract_from_filename(filename: str) -> str | None:
    """Extract ISBN from filename patterns.

    Common patterns:
    - 9781491950395_Head_First_Agile.pdf
    - Head First Agile [9781491950395].epub
    - Author - Title -- 9781491950395 -- hash.epub
    - ISBN-9781491950395.pdf
    """
    import re

    # Find any 13-digit sequence starting with 978/979
    matches = re.findall(r"97[89]\d{10}", filename.replace("-", "").replace(" ", ""))
    for m in matches:
        if _verify_isbn13(m):
            return m
    # Try 10-digit ISBN (less common in filenames)
    matches10 = re.findall(r"(?<![\d])\d{9}[\dXx](?![\d])", filename.replace("-", ""))
    for m in matches10:
        cleaned = _clean_isbn(m)
        if cleaned:
            return cleaned
    return None


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

    # Phase 1.5a: PDF metadata (Subject, Keywords, Comments fields)
    if not isbn and row["format"] == "pdf":
        isbn = extract_from_pdf_metadata(row["file_path"])

    # Phase 1.5b: Filename ISBN (fast, no file parsing needed)
    if not isbn:
        book_row = await fetch_one("SELECT original_filename FROM books WHERE id = $1", UUID(book_id))
        if book_row and book_row.get("original_filename"):
            isbn = extract_from_filename(book_row["original_filename"])

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

    # Store extracted metadata (publisher, edition, translator, printer)
    import json

    meta_update = {
        k: v
        for k, v in {
            "publisher": extra.get("publisher"),
            "printer": extra.get("printer"),
            "edition": extra.get("edition"),
            "translator": extra.get("translator"),
            "digital_production": extra.get("digital_production"),
            "original_title": extra.get("original_title"),
            "depot_legal": extra.get("depot_legal"),
            "copyright_year": extra.get("copyright_year"),
            "all_isbns": extra.get("all_isbns"),
        }.items()
        if v
    }
    if meta_update:
        await execute(
            "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
            json.dumps(meta_update),
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
    """Detect country/region from ISBN prefix.
    Uses: 1) Official ISBN Range Message (285 groups), 2) isbnlib, 3) our static map."""
    from brainycat.isbn_ranges import lookup as _range_lookup

    range_info = _range_lookup(isbn)

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
            if range_info:
                result["official_agency"] = range_info["agency"]
                result["official_prefix"] = range_info["prefix"]
            if masked:
                result["masked"] = masked
            if publisher_prefix:
                result["publisher_prefix"] = publisher_prefix
            return result

    # Fallback: isbnlib info only
    if range_info:
        return {
            "region": range_info["agency"],
            "countries": [],
            "best_sources": ["google_books"],
            "official_agency": range_info["agency"],
            "official_prefix": range_info["prefix"],
            "language_info": info,
            "masked": masked,
        }
    if info:
        return {"region": info, "countries": [], "best_sources": ["google_books"], "language_info": info, "masked": masked}
    return None


# Known publisher prefixes (from ISBN range data)
PUBLISHER_PREFIXES: dict[str, str] = {
    "978-2-07": "Gallimard",
    "978-2-253": "Le Livre de Poche",
    "978-2-070": "Gallimard",
    "978-2-01": "Hachette",
    "978-2-221": "Robert Laffont",
    "978-2-266": "Pocket",
    "978-2-290": "J'ai Lu",
    "978-2-08": "Flammarion",
    "978-2-02": "Seuil",
    "978-2-226": "Albin Michel",
    "978-2-246": "Grasset",
    "978-0-14": "Penguin",
    "978-0-06": "HarperCollins",
    "978-0-316": "Little Brown",
    "978-0-375": "Random House",
    "978-0-385": "Doubleday",
    "978-0-399": "Putnam",
    "978-0-451": "Signet/NAL",
    "978-0-553": "Bantam",
    "978-0-671": "Simon & Schuster",
    "978-0-7432": "Simon & Schuster",
    "978-1-250": "St. Martin's",
    "978-1-4013": "Hachette US",
    "978-1-5011": "Simon & Schuster",
    "978-3-518": "Suhrkamp",
    "978-3-423": "dtv",
    "978-3-596": "Fischer",
    "978-4-04": "Kadokawa",
    "978-4-06": "Kodansha",
    "978-4-08": "Shueisha",
    "978-88-06": "Einaudi",
    "978-88-04": "Mondadori",
}


def isbn_to_publisher(isbn: str) -> str | None:
    """Detect publisher from ISBN prefix using known ranges."""
    if not isbn or len(isbn) < 10:
        return None
    try:
        import isbnlib

        masked = isbnlib.mask(isbn)
        if masked:
            parts = masked.split("-")
            for prefix_len in range(len(parts), 2, -1):
                prefix = "-".join(parts[:prefix_len])
                if prefix in PUBLISHER_PREFIXES:
                    return PUBLISHER_PREFIXES[prefix]
    except Exception:
        pass
    # Fallback: check our static map
    for prefix, publisher in sorted(PUBLISHER_PREFIXES.items(), key=lambda x: len(x[0]), reverse=True):
        flat = prefix.replace("-", "")
        if isbn.startswith(flat):
            return publisher
    return None


async def isbn_from_cover_search(book_id: str) -> str | None:
    """Try to identify a book by its cover image via Google Books cover matching.

    Extracts cover, searches Google Books by title (from OCR of cover if needed),
    then confirms match by comparing cover images.
    """
    import os
    from uuid import UUID
    from brainycat.db import fetch_one
    import httpx

    book = await fetch_one(
        "SELECT b.title, b.cover_path, b.isbn FROM books b WHERE b.id = $1",
        UUID(book_id),
    )
    if not book or book.get("isbn"):
        return book.get("isbn") if book else None

    # If we have a title, search Google Books and grab ISBN from result
    if book.get("title") and len(book["title"]) > 5:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://www.googleapis.com/books/v1/volumes",
                    params={"q": book["title"], "maxResults": 3},
                )
                if r.status_code == 200:
                    for item in r.json().get("items", []):
                        info = item.get("volumeInfo", {})
                        for ident in info.get("industryIdentifiers", []):
                            if ident["type"] == "ISBN_13":
                                # Verify relevance before returning
                                from brainycat.relevance_guard import is_relevant

                                if is_relevant(book["title"], info.get("title", ""), ident["identifier"], None):
                                    return ident["identifier"]
        except Exception:
            pass

    return None
