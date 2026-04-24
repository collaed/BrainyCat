"""Background scheduler — periodic enrichment, fingerprinting, duplicate detection."""

from __future__ import annotations

import asyncio
import contextlib

from brainycat.logging import log


async def start_scheduler() -> None:
    asyncio.create_task(_enrichment_loop())  # noqa: RUF006
    asyncio.create_task(_fingerprint_loop())  # noqa: RUF006
    asyncio.create_task(_title_cleanup_loop())  # noqa: RUF006
    asyncio.create_task(_ocr_loop())  # noqa: RUF006
    await log.ainfo("scheduler_started")


async def _enrichment_loop() -> None:
    await asyncio.sleep(15)
    while True:
        try:
            from brainycat.db import get_pool
            from brainycat.metadata import enrich_book

            pool = await get_pool()
            enriched = 0
            # Use FOR UPDATE SKIP LOCKED to prevent concurrent enrichment of same book
            async with pool.acquire() as conn, conn.transaction():
                rows = await conn.fetch(
                    "SELECT id, title FROM books WHERE quality_score < 50 ORDER BY updated_at ASC LIMIT 3 FOR UPDATE SKIP LOCKED"
                )
                for row in rows:
                    await conn.execute("UPDATE books SET updated_at = now() WHERE id = $1", row["id"])

            for row in rows:
                result = await enrich_book(str(row["id"]))
                if result.get("enriched"):
                    enriched += 1
            if enriched:
                await log.ainfo("auto_enriched", count=enriched, batch=len(rows))
        except Exception as e:
            await log.awarning("enrichment_error", error=str(e))
        await asyncio.sleep(60)


async def _fingerprint_loop() -> None:
    await asyncio.sleep(45)
    while True:
        try:
            # Generate embeddings for books without them
            from brainycat.db import fetch_all as _fa
            from brainycat.embeddings import embed_book

            unembedded = await _fa("SELECT id FROM books WHERE embedding IS NULL AND description IS NOT NULL LIMIT 20")
            for r in unembedded:
                with contextlib.suppress(Exception):
                    await embed_book(str(r["id"]))

            from brainycat.fingerprints import compute_all_fingerprints, find_duplicates_by_content

            result = await compute_all_fingerprints(batch_size=10)
            if result["computed"] > 0:
                await log.ainfo("fingerprints", **result)

            if result.get("pending", 0) == 0:
                dupes = await find_duplicates_by_content(batch_size=20)
                if dupes["new_matches"] > 0:
                    await log.ainfo("dupes_found", **dupes)
        except Exception as e:
            await log.awarning("fingerprint_error", error=str(e))
        await asyncio.sleep(30)


async def _title_cleanup_loop() -> None:
    """Background: extract ISBNs from filenames, fix titles from API."""
    await asyncio.sleep(60)  # Wait 1 min before starting
    while True:
        try:
            from brainycat.title_cleanup import run_title_cleanup_cycle

            result = await run_title_cleanup_cycle()
            isbn_found = result.get("isbn_from_filename", {}).get("found", 0)
            titles_fixed = result.get("api_title_fix", {}).get("fixed", 0)

            # Also classify untagged books
            from brainycat.db import execute, fetch_all, fetch_one
            from brainycat.http_client import get_client
            from brainycat.rate_limit import rate_limiter

            untagged = await fetch_all("""
                SELECT b.id, b.isbn FROM books b
                WHERE b.isbn IS NOT NULL AND length(b.isbn) >= 10
                  AND NOT EXISTS (SELECT 1 FROM books_tags bt WHERE bt.book_id = b.id)
                LIMIT 5
            """)
            genres_added = 0
            for row in untagged:
                try:
                    await rate_limiter.wait("google")
                    c = get_client()
                    resp = await c.get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{row['isbn']}&maxResults=1")
                    if resp.status_code == 200:
                        items = resp.json().get("items", [])
                        if items:
                            for cat in items[0].get("volumeInfo", {}).get("categories", [])[:5]:
                                await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", cat.strip())
                                tag = await fetch_one("SELECT id FROM tags WHERE name = $1", cat.strip())
                                if tag:
                                    await execute(
                                        "INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                                        row["id"],
                                        tag["id"],
                                    )
                                    genres_added += 1
                except Exception:
                    pass
            if isbn_found or titles_fixed or genres_added:
                await log.ainfo("title_cleanup", isbn_found=isbn_found, titles_fixed=titles_fixed, genres_added=genres_added)
        except Exception as e:
            await log.awarning("title_cleanup_error", error=str(e))
        await asyncio.sleep(60)  # Every 60s


async def _ocr_loop() -> None:
    """Keep one OCR job in flight on Intello. Poll status, submit next."""
    await asyncio.sleep(90)
    while True:
        try:
            from brainycat.db import execute, fetch_all, fetch_one
            from brainycat.http_client import get_client

            # 1. Poll pending OCR jobs
            pending = await fetch_all(
                "SELECT id, book_id, remote_job_id FROM async_jobs WHERE job_type = 'ocr' AND status = 'submitted' LIMIT 5"
            )
            client = get_client()
            for job in pending:
                try:
                    resp = await client.get(f"http://intello:8000/api/v1/ocr/jobs/{job['remote_job_id']}", timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("status", "unknown")
                        if status == "complete":
                            await execute("UPDATE async_jobs SET status = 'complete' WHERE id = $1", job["id"])
                            # Download result via proper API endpoint
                            result_path = data.get("result_path")
                            if result_path:
                                dl = await client.get(
                                    f"http://intello:8000/api/v1/ocr/jobs/{job['remote_job_id']}/result",
                                    timeout=120,
                                )
                                if dl.status_code == 200:
                                    import os

                                    from brainycat.storage import book_dir

                                    out = os.path.join(book_dir(str(job["book_id"])), "ocr_result.pdf")
                                    with open(out, "wb") as f:
                                        f.write(dl.content)
                                    await execute(
                                        "INSERT INTO book_files (book_id, file_path, format, file_size, file_name) "
                                        "VALUES ($1, $2, 'pdf', $3, 'ocr_result.pdf') ON CONFLICT DO NOTHING",
                                        job["book_id"],
                                        out,
                                        len(dl.content),
                                    )
                            await log.ainfo("ocr_complete", book_id=str(job["book_id"]))
                        elif status == "failed":
                            await execute("UPDATE async_jobs SET status = 'failed' WHERE id = $1", job["id"])
                except Exception:
                    pass

            # 2. If no pending jobs, submit the next scanned PDF without OCR
            active = await fetch_one("SELECT id FROM async_jobs WHERE job_type = 'ocr' AND status = 'submitted' LIMIT 1")
            if not active:
                candidate = await fetch_one("""
                    SELECT b.id, bf.file_path, b.language FROM books b
                    JOIN book_files bf ON bf.book_id = b.id AND bf.format = 'pdf' AND bf.file_size > 500000
                    WHERE NOT EXISTS (SELECT 1 FROM async_jobs aj WHERE aj.book_id = b.id AND aj.job_type = 'ocr')
                    ORDER BY bf.file_size ASC LIMIT 1
                """)
                if candidate:
                    import os

                    if os.path.isfile(candidate["file_path"]):
                        lang = (candidate["language"] or "eng")[:3]
                        with open(candidate["file_path"], "rb") as f:
                            resp = await client.post(
                                "http://intello:8000/api/v1/ocr/jobs",
                                files={"file": ("book.pdf", f, "application/pdf")},
                                data={"language": lang, "output": "searchable_pdf"},
                                timeout=60,
                            )
                        if resp.status_code == 200:
                            import uuid

                            remote_id = resp.json().get("job_id", "")
                            await execute(
                                "INSERT INTO async_jobs (id, book_id, job_type, remote_job_id, status) VALUES ($1, $2, 'ocr', $3, 'submitted')",
                                uuid.uuid4(),
                                candidate["id"],
                                remote_id,
                            )
                            await log.ainfo("ocr_submitted", book_id=str(candidate["id"]))
        except Exception as e:
            await log.awarning("ocr_loop_error", error=str(e))
        await asyncio.sleep(120)  # Check every 2 minutes
