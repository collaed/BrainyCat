"""OCR and PDF utilities — cover extraction, text OCR, rotation detection."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

from brainycat.db import fetch_one
from brainycat.jobs import create_job, run_in_background, update_job


def extract_pdf_cover(pdf_path: str, output_path: str) -> bool:
    """Extract first page of PDF as cover image."""
    try:
        import fitz

        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return False
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for quality
        # Scale down to cover size
        if pix.width > 600:
            scale = 600 / pix.width
            pix = page.get_pixmap(matrix=fitz.Matrix(scale * 2, scale * 2))
        pix.save(output_path)
        doc.close()
        return os.path.isfile(output_path)
    except Exception:
        return False


async def ocr_pdf(book_id: str, user_id: str | None = None) -> str:
    """OCR a scanned PDF — makes it searchable. Returns job ID."""
    job_id = await create_job("ocr", book_id=book_id, user_id=user_id)

    async def _run() -> None:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1", UUID(book_id))
        if not file_row:
            await update_job(job_id, status="failed", error="No PDF file")
            return

        src = file_row["file_path"]
        dest = src.replace(".pdf", "_ocr.pdf")

        await update_job(job_id, progress=10)

        proc = await asyncio.create_subprocess_exec(
            "ocrmypdf",
            "--rotate-pages",  # auto-detect rotated pages
            "--deskew",  # fix skewed scans
            "--clean",  # clean up scan artifacts
            "--skip-text",  # skip pages that already have text
            "-l",
            "eng+fra+deu+spa",  # languages
            src,
            dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        await update_job(job_id, progress=90)

        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            # Replace original with OCR'd version
            os.replace(dest, src)
            await update_job(job_id, progress=100)
        else:
            await update_job(job_id, status="failed", error=stderr.decode(errors="replace")[:300])

    await run_in_background(job_id, _run())
    return job_id
