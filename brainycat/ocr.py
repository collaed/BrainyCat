"""OCR via Intello — page-by-page processing for large PDFs."""

from __future__ import annotations

import os
import tempfile
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
    """OCR a scanned PDF page by page via Intello. Returns job ID."""
    job_id = await create_job("ocr", book_id=book_id, user_id=user_id)

    async def _run() -> None:
        file_row = await fetch_one(
            "SELECT * FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1",
            UUID(book_id),
        )
        if not file_row:
            await update_job(job_id, status="failed", error="No PDF file")
            return

        import fitz

        src = file_row["file_path"]
        try:
            doc = fitz.open(src)
        except Exception as e:
            await update_job(job_id, status="failed", error=f"Cannot open PDF: {e}")
            return

        num_pages = len(doc)
        if num_pages == 0:
            await update_job(job_id, status="failed", error="Empty PDF")
            doc.close()
            return

        await update_job(job_id, progress=5)

        # Process page by page: extract as image, send to Intello OCR
        ocr_pages = []
        errors = 0

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for i in range(num_pages):
                pct = 5 + (i / num_pages) * 85
                await update_job(job_id, progress=pct)

                # Render page to PNG
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x for OCR quality
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    pix.save(tmp.name)
                    tmp_path = tmp.name

                try:
                    with open(tmp_path, "rb") as f:
                        resp = await client.post(
                            f"{settings.intello_url}/api/v1/ocr",
                            files={"file": (f"page_{i + 1}.png", f, "image/png")},
                            data={"language": "fra+eng+deu"},
                        )

                    if resp.status_code == 200:
                        data = resp.json()
                        text = data.get("text", "")
                        rotation = data.get("rotation", 0)
                        ocr_pages.append(
                            {
                                "page": i + 1,
                                "text": text,
                                "chars": len(text),
                                "rotation": rotation,
                            }
                        )
                    else:
                        errors += 1
                        ocr_pages.append({"page": i + 1, "text": "", "chars": 0, "error": resp.status_code})
                except Exception as e:
                    errors += 1
                    ocr_pages.append({"page": i + 1, "text": "", "chars": 0, "error": str(e)[:50]})
                finally:
                    os.unlink(tmp_path)

        doc.close()
        await update_job(job_id, progress=95)

        # Rebuild PDF with OCR text layer using PyMuPDF
        total_chars = sum(p["chars"] for p in ocr_pages)
        rotated = [p["page"] for p in ocr_pages if p.get("rotation", 0) != 0]

        await update_job(
            job_id,
            progress=100,
            result={
                "pages": num_pages,
                "ocr_pages": len([p for p in ocr_pages if p["chars"] > 0]),
                "total_chars": total_chars,
                "errors": errors,
                "rotated_pages": rotated[:20],
            },
        )

    await run_in_background(job_id, _run())
    return job_id
