"""Post-process OCR PDFs: replace text-image regions with real text, keep illustrations."""

from __future__ import annotations

import contextlib
import os
from typing import Any

import fitz  # PyMuPDF


async def optimize_ocr_pdf(ocr_path: str, output_path: str | None = None) -> dict[str, Any]:
    """Optimize an OCR'd PDF by replacing text regions with real text.

    For each page:
    1. Extract the text layer (from OCR) with positions
    2. Identify image regions that contain illustrations vs text-as-image
    3. Keep illustration images, remove text-image regions
    4. Re-render text blocks as real PDF text on transparent background

    Result: much smaller PDF that's fully searchable with preserved illustrations.
    """
    if not output_path:
        output_path = ocr_path.replace(".pdf", "_optimized.pdf")

    src = fitz.open(ocr_path)
    dst = fitz.open()  # new empty PDF

    pages_optimized = 0
    orig_size = os.path.getsize(ocr_path)

    for page_num in range(len(src)):
        src_page = src[page_num]
        width = src_page.rect.width
        height = src_page.rect.height

        # Get text blocks with positions
        text_blocks = src_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = text_blocks.get("blocks", [])

        # Get images on this page
        src_page.get_images(full=True)

        # Classify: is this page mostly text or mostly illustration?
        text_area = 0
        image_area = 0
        text_content = []

        for block in blocks:
            if block["type"] == 0:  # text block
                bbox = fitz.Rect(block["bbox"])
                text_area += bbox.width * bbox.height
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_content.append(
                            {
                                "text": span["text"],
                                "bbox": fitz.Rect(span["bbox"]),
                                "size": span["size"],
                                "font": span.get("font", "helv"),
                                "color": span.get("color", 0),
                            }
                        )
            elif block["type"] == 1:  # image block
                bbox = fitz.Rect(block["bbox"])
                image_area += bbox.width * bbox.height

        page_area = width * height
        text_area / max(page_area, 1)
        image_ratio = image_area / max(page_area, 1)

        # Create new page
        new_page = dst.new_page(width=width, height=height)

        if image_ratio > 0.3:
            # Page has significant illustrations — keep the original page image
            # but only for illustration regions, render text as real text
            # For simplicity: if >70% image, keep whole page as image
            if image_ratio > 0.7:
                # Full illustration page (diagrams, photos) — keep as-is
                new_page.show_pdf_page(new_page.rect, src, page_num)
            else:
                # Mixed page: extract and keep only illustration images
                # Render text as real text
                for block in blocks:
                    if block["type"] == 1:  # image block
                        bbox = fitz.Rect(block["bbox"])
                        clip = fitz.Rect(bbox)
                        # Copy just this image region from source
                        new_page.show_pdf_page(clip, src, page_num, clip=clip)

                # Render text blocks
                for span in text_content:
                    if span["text"].strip():
                        fontsize = max(6, min(span["size"], 24))
                        try:
                            new_page.insert_text(
                                span["bbox"].tl,  # top-left point
                                span["text"],
                                fontsize=fontsize,
                                fontname="helv",
                                color=(0, 0, 0),
                            )
                        except Exception:  # noqa: SIM105
                            pass
                pages_optimized += 1
        else:
            # Text-heavy page — render as pure text (no background image)
            for span in text_content:
                if span["text"].strip():
                    fontsize = max(6, min(span["size"], 24))
                    with contextlib.suppress(Exception):
                        new_page.insert_text(
                            span["bbox"].tl,
                            span["text"],
                            fontsize=fontsize,
                            fontname="helv",
                            color=(0, 0, 0),
                        )
            pages_optimized += 1

    dst.save(output_path, deflate=True, garbage=4)
    new_size = os.path.getsize(output_path)
    src.close()
    dst.close()

    return {
        "ok": True,
        "pages": len(src),
        "pages_optimized": pages_optimized,
        "original_size_mb": round(orig_size / 1048576, 1),
        "optimized_size_mb": round(new_size / 1048576, 1),
        "reduction_pct": round((1 - new_size / max(orig_size, 1)) * 100),
    }
