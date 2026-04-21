"""OCR via Intello service — no local tesseract needed."""

from __future__ import annotations

import os
from uuid import UUID

import httpx

from brainycat.config import settings
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
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        if pix.width > 600:
            scale = 600 / pix.width
            pix = page.get_pixmap(matrix=fitz.Matrix(scale * 1.5, scale * 1.5))
        pix.save(output_path)
        doc.close()
        return os.path.isfile(output_path)
    except Exception:
        return False


async def ocr_pdf(book_id: str, user_id: str | None = None) -> str:
    """OCR a scanned PDF via Intello's OCR service. Returns job ID."""
    job_id = await create_job("ocr", book_id=book_id, user_id=user_id)

    async def _run() -> None:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1", UUID(book_id))
        if not file_row:
            await update_job(job_id, status="failed", error="No PDF file")
            return

        await update_job(job_id, progress=10)

        # Send PDF to Intello OCR endpoint
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                with open(file_row["file_path"], "rb") as f:
                    resp = await client.post(
                        f"{settings.intello_url}/api/v1/ocr/pdf",
                        files={"file": (os.path.basename(file_row["file_path"]), f, "application/pdf")},
                        data={"language": "eng+fra+deu+spa", "searchable": "true"},
                    )

                await update_job(job_id, progress=80)

                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/pdf"):
                    # Replace original with OCR'd version
                    with open(file_row["file_path"], "wb") as out:
                        out.write(resp.content)
                    await update_job(job_id, progress=100)
                else:
                    error = resp.text[:300] if resp.status_code != 200 else "No PDF returned"
                    await update_job(job_id, status="failed", error=error)
        except Exception as e:
            await update_job(job_id, status="failed", error=str(e)[:300])

    await run_in_background(job_id, _run())
    return job_id
