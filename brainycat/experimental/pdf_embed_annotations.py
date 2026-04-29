"""PDF annotation embedding — write highlights INTO the PDF file.

Uses PyMuPDF to add highlight annotations directly to the PDF,
so they survive if the user downloads the file.

Config: BRAINYCAT_EXP_PDF_EMBED=1
"""

from __future__ import annotations

from typing import Any


async def embed_annotations(book_id: str) -> dict[str, Any]:
    """Write stored annotations into the actual PDF file."""
    import fitz

    from uuid import UUID
    from brainycat.db import fetch_all, fetch_one

    row = await fetch_one(
        "SELECT bf.file_path FROM book_files bf WHERE bf.book_id = $1 AND bf.format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row or not row["file_path"]:
        return {"error": "no pdf found"}

    annotations = await fetch_all(
        "SELECT page_num, text, quad_points FROM annotations WHERE book_id = $1 AND page_num IS NOT NULL",
        UUID(book_id),
    )
    if not annotations:
        return {"embedded": 0, "reason": "no annotations with page numbers"}

    doc = fitz.open(row["file_path"])
    embedded = 0

    for ann in annotations:
        page_num = ann["page_num"]
        if page_num < 0 or page_num >= len(doc):
            continue
        page = doc[page_num]
        # Search for the text on the page to get quads
        text = ann["text"] or ""
        if not text:
            continue
        instances = page.search_for(text[:100])
        if instances:
            highlight = page.add_highlight_annot(instances)
            if highlight:
                highlight.set_colors(stroke=(1, 0.8, 0))  # Yellow
                highlight.update()
                embedded += 1

    if embedded:
        doc.save(row["file_path"], incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()

    return {"embedded": embedded, "total_annotations": len(annotations)}
