"""OCR — submit scanned PDFs to Intello, scheduler handles polling."""

from __future__ import annotations

import os
import uuid

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client


def extract_pdf_cover(pdf_path: str, output_path: str) -> bool:
    """Extract cover image from first page of a PDF."""
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
        return True
    except Exception:
        return False


async def ocr_pdf(book_id: str, user_id: str | None = None) -> str:
    """Submit a PDF for OCR via Intello. Returns job ID. Scheduler polls for results."""
    from uuid import UUID

    file_row = await fetch_one(
        "SELECT file_path, file_size FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not file_row:
        return ""

    # Detect language
    book = await fetch_one("SELECT language FROM books WHERE id = $1", UUID(book_id))
    lang = (book["language"] if book else None) or "eng"

    # Submit to Intello
    client = get_client()
    src = file_row["file_path"]

    # Split large PDFs (>30MB) into chunks
    submit_path = src
    if (file_row["file_size"] or 0) > 30_000_000:
        from brainycat.scheduler import _split_pdf_chunk

        chunk = await _split_pdf_chunk(src, 30_000_000)
        if chunk:
            submit_path = chunk

    try:
        with open(submit_path, "rb") as f:
            resp = await client.post(
                f"{settings.intello_url}/api/v1/ocr/jobs",
                files={"file": ("book.pdf", f, "application/pdf")},
                data={"language": lang, "output": "hybrid"},
                timeout=90,
            )
    finally:
        if submit_path != src and os.path.exists(submit_path):
            os.unlink(submit_path)

    if resp.status_code != 200:
        return ""

    remote_id = resp.json().get("job_id", "")
    job_id = uuid.uuid4()
    await execute(
        "INSERT INTO async_jobs (id, book_id, job_type, remote_job_id, status) VALUES ($1, $2, 'ocr', $3, 'submitted')",
        job_id,
        UUID(book_id),
        remote_id,
    )
    return str(job_id)
