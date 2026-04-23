"""Ingest pipeline — auto-convert, clean, enrich, and store books.

Upload flow:
1. Detect format
2. Convert to EPUB3 canonical (except PDF — kept as-is)
3. Clean (encoding, CSS, images)
4. ISBN scan + parallel enrichment (10 sources)
5. Writeback metadata into EPUB3
6. Store both original + canonical
7. Push to Calibre via plugin

Delivery flow (device-aware):
- Regular Kindle → AZW3 (from EPUB3)
- Kindle Scribe → PDF (for handwriting annotations)
- Kobo → KEPUB
- Generic → EPUB3
- Workbooks/textbooks → always PDF
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one


async def ingest_book(book_id: str) -> dict[str, Any]:
    """Run the full ingest pipeline on a book."""
    row = await fetch_one(
        """
        SELECT bf.file_path, bf.format, b.title, b.is_workbook
        FROM book_files bf JOIN books b ON b.id = bf.book_id
        WHERE bf.book_id = $1 ORDER BY
            CASE bf.format WHEN 'epub' THEN 1 WHEN 'pdf' THEN 2 ELSE 3 END
        LIMIT 1
    """,
        UUID(book_id),
    )
    if not row:
        return {"error": "no file"}

    src_format = row["format"]
    src_path = row["file_path"]
    steps_done = []

    # Step 1: Convert to EPUB3 canonical (except PDF)
    canonical_path = None
    if src_format == "epub":
        canonical_path = src_path  # Already EPUB
        steps_done.append("epub_detected")
    elif src_format == "pdf":
        # Keep PDF as-is — don't force-convert (quality too poor)
        steps_done.append("pdf_kept_as_is")
    elif shutil.which("ebook-convert"):
        canonical_path = src_path.rsplit(".", 1)[0] + ".epub"
        if not os.path.isfile(canonical_path):
            proc = await asyncio.create_subprocess_exec(
                "ebook-convert",
                src_path,
                canonical_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0 and os.path.isfile(canonical_path):
                await execute(
                    "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,'epub',$3,$4) ON CONFLICT DO NOTHING",
                    uuid4(),
                    UUID(book_id),
                    canonical_path,
                    os.path.basename(canonical_path),
                )
                steps_done.append(f"converted_{src_format}_to_epub")
            else:
                steps_done.append(f"conversion_failed_{src_format}")

    # Step 2: ISBN scan
    from brainycat.isbn import extract_and_store_isbn

    isbn_result = await extract_and_store_isbn(book_id)
    if isbn_result.get("ok"):
        steps_done.append("isbn_extracted")

    # Step 3: Enrich from all sources
    from brainycat.metadata import enrich_book

    enrich_result = await enrich_book(book_id)
    if enrich_result.get("enriched"):
        steps_done.append(f"enriched_{enrich_result.get('sources', 0)}_sources")

    # Step 4: Generate embedding
    from brainycat.embeddings import embed_book

    await embed_book(book_id)
    steps_done.append("embedded")

    # Step 5: Writeback metadata into EPUB
    if canonical_path and os.path.isfile(canonical_path):
        from brainycat.writeback import writeback_metadata

        wb = await writeback_metadata(book_id)
        if wb.get("ok"):
            steps_done.append("metadata_written_back")

    return {"ok": True, "steps": steps_done}


def choose_delivery_format(
    target_device: str,
    available_formats: list[str],
    is_workbook: bool = False,
) -> str:
    """Choose the best format for delivery based on target device.

    Kindle Scribe needs PDF for handwriting annotations.
    Regular Kindle prefers AZW3.
    Kobo prefers KEPUB.
    Workbooks/textbooks always go as PDF.
    """
    if is_workbook:
        return "pdf"

    device = target_device.lower()

    if "scribe" in device:
        # Kindle Scribe: PDF for handwriting on pages
        if "pdf" in available_formats:
            return "pdf"
        return "pdf"  # Will need conversion

    if "kindle" in device:
        # Regular Kindle: AZW3 > MOBI > EPUB
        for fmt in ("azw3", "mobi", "epub"):
            if fmt in available_formats:
                return fmt
        return "azw3"  # Will need conversion

    if "kobo" in device:
        if "kepub" in available_formats:
            return "kepub"
        return "kepub"  # Will need conversion

    # Generic: EPUB3 preferred
    if "epub" in available_formats:
        return "epub"
    return "epub"
