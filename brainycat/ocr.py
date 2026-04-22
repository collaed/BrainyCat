"""OCR via Intello — job-based for large PDFs, produces searchable PDF with images."""

from __future__ import annotations

import os
from uuid import UUID

import httpx

from brainycat.config import settings
from brainycat.db import fetch_one
from brainycat.jobs import create_job, run_in_background, update_job


def extract_pdf_cover(pdf_path: str, output_path: str) -> bool:
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
    """OCR a scanned PDF via Intello's job-based endpoint. Returns BrainyCat job ID."""
    job_id = await create_job("ocr", book_id=book_id, user_id=user_id)

    async def _run() -> None:
        file_row = await fetch_one(
            "SELECT * FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1",
            UUID(book_id),
        )
        if not file_row:
            await update_job(job_id, status="failed", error="No PDF file")
            return

        src = file_row["file_path"]
        await update_job(job_id, progress=5)

        # Step 1: Submit OCR job to Intello
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                with open(src, "rb") as f:
                    resp = await client.post(
                        f"{settings.intello_url}/api/v1/ocr/jobs",
                        files={"file": (os.path.basename(src), f, "application/pdf")},
                        data={"language": "fra+eng+deu", "output": "searchable_pdf"},
                    )
                if resp.status_code != 200:
                    await update_job(job_id, status="failed", error=f"Intello rejected: {resp.status_code}")
                    return
                intello_job = resp.json()
                intello_job_id = intello_job.get("job_id")
                if not intello_job_id:
                    await update_job(job_id, status="failed", error=f"No job ID: {intello_job}")
                    return
        except Exception as e:
            await update_job(job_id, status="failed", error=f"Submit failed: {e}")
            return

        await update_job(job_id, progress=10)

        # Step 2: Poll Intello job until complete
        import asyncio

        for _ in range(600):  # max 10 minutes
            await asyncio.sleep(3)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(f"{settings.intello_url}/api/v1/ocr/jobs/{intello_job_id}")
                    if resp.status_code != 200:
                        continue
                    status = resp.json()
                    pct = status.get("progress", 0)
                    await update_job(job_id, progress=10 + pct * 0.8)

                    if status.get("status") == "complete":
                        break
                    if status.get("status") == "failed":
                        await update_job(job_id, status="failed", error=status.get("error", "Intello OCR failed"))
                        return
            except Exception:
                continue

        # Step 3: Download the searchable PDF result
        await update_job(job_id, progress=92)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.get(f"{settings.intello_url}/api/v1/ocr/jobs/{intello_job_id}/result")
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/pdf"):
                    # Replace original with searchable PDF
                    with open(src, "wb") as out:
                        out.write(resp.content)
                    await update_job(job_id, progress=100)
                else:
                    # Maybe it returned JSON with text

                    try:
                        data = resp.json()
                        await update_job(
                            job_id,
                            progress=100,
                            result={"pages": data.get("pages", 0), "chars": data.get("total_chars", 0)},
                        )
                    except Exception:
                        await update_job(job_id, status="failed", error="Could not download result")
        except Exception as e:
            await update_job(job_id, status="failed", error=f"Download failed: {e}")

    await run_in_background(job_id, _run())
    return job_id
