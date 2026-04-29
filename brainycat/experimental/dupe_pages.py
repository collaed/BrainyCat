"""Duplicate page detection in PDFs.

Scanned PDFs often have repeated cover pages, blank pages, or
duplicate content. This detects them via image hashing.

Config: BRAINYCAT_EXP_DUPE_PAGES=1
"""

from __future__ import annotations

import hashlib
from typing import Any


async def detect_duplicate_pages(book_id: str) -> dict[str, Any]:
    """Find duplicate pages in a PDF by comparing page image hashes."""
    from uuid import UUID

    import fitz

    from brainycat.db import fetch_one

    row = await fetch_one(
        "SELECT bf.file_path FROM book_files bf WHERE bf.book_id = $1 AND bf.format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row or not row["file_path"]:
        return {"error": "no pdf"}

    doc = fitz.open(row["file_path"])
    hashes: dict[str, list[int]] = {}

    for i in range(len(doc)):
        page = doc[i]
        # Low-res pixmap for fast comparison
        pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
        h = hashlib.md5(pix.samples).hexdigest()
        hashes.setdefault(h, []).append(i)

    doc.close()

    duplicates = {h: pages for h, pages in hashes.items() if len(pages) > 1}
    return {
        "total_pages": sum(len(p) for p in hashes.values()),
        "unique_pages": len(hashes),
        "duplicate_groups": [{"pages": pages, "count": len(pages)} for pages in duplicates.values()],
        "pages_to_remove": [p for pages in duplicates.values() for p in pages[1:]],
    }
