"""Background scheduler — supervised tasks with proper error handling."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from brainycat.logging import log

# ── Supervised task runner ────────────────────────────────────────────────
_tasks: list[asyncio.Task[None]] = []


async def start_scheduler() -> None:
    """Start all background loops with supervision."""
    _tasks.append(asyncio.create_task(_supervised("watcher", _watcher_loop, 10)))

    loops = [
        ("enrichment", _enrichment_loop, 60),
        ("fingerprint", _fingerprint_loop, 30),
        ("title_cleanup", _title_cleanup_loop, 90),
        ("format_stack", _format_stack_loop, 300),
        ("ocr", _ocr_loop, 120),
    ]
    for name, fn, interval in loops:
        task = asyncio.create_task(_supervised(name, fn, interval))
        _tasks.append(task)
    await log.ainfo("scheduler_started", tasks=len(loops))


async def _supervised(name: str, fn: Any, interval: int) -> None:
    """Run a loop function with supervision — restart on crash, log all errors."""
    await asyncio.sleep(15 + hash(name) % 30)  # stagger startup
    while True:
        try:
            await fn()
        except Exception as e:
            # Log but don't die — the while True keeps us alive
            with contextlib.suppress(Exception):
                await log.awarning(f"{name}_error", error=str(e)[:200])
        await asyncio.sleep(interval)


# ── Enrichment (with row locking) ────────────────────────────────────────
async def _enrichment_loop() -> None:
    from brainycat import db
    from brainycat.db import get_pool
    from brainycat.metadata import enrich_book

    pool = await get_pool()
    # Step 1: Find least-tried books (no lock — aggregates not allowed with FOR UPDATE)
    candidates = await db.fetch_all(
        "SELECT b.id, b.title FROM books b "
        "LEFT JOIN (SELECT book_id, count(*) as cnt FROM enrichment_log GROUP BY book_id) a ON a.book_id = b.id "
        "LEFT JOIN (SELECT book_id, max(created_at) as last_try FROM enrichment_log GROUP BY book_id) lt ON lt.book_id = b.id "
        "WHERE b.quality_score < 95 "
        "AND (lt.last_try IS NULL OR lt.last_try < now() - interval '7 days' * (COALESCE(a.cnt, 0) / 10.0 + 1)) "
        "ORDER BY b.quality_score ASC, COALESCE(a.cnt, 0) ASC, b.updated_at ASC "
        "LIMIT 10"
    )
    # Step 2: Lock 3 one-by-one (FOR UPDATE SKIP LOCKED per row)
    rows = []
    async with pool.acquire() as conn, conn.transaction():
        for c in candidates:
            if len(rows) >= 3:
                break
            locked = await conn.fetchrow("SELECT id, title FROM books WHERE id = $1 FOR UPDATE SKIP LOCKED", c["id"])
            if locked:
                await conn.execute("UPDATE books SET updated_at = now() WHERE id = $1", locked["id"])
                rows.append(locked)

    # Enrich all locked books in parallel (not sequentially)
    async def _enrich_one(row):
        try:
            async with asyncio.timeout(30):
                result = await enrich_book(str(row["id"]))
                return 1 if result.get("enriched") else 0
        except TimeoutError:
            await log.awarning("enrichment_timeout", book_id=str(row["id"]))
        except Exception:
            pass
        return 0

    results = await asyncio.gather(*[_enrich_one(r) for r in rows])
    enriched = sum(results)
    # Stage 2: Deep enrich for books still below 50 after standard enrichment
    for row in rows:
        book = await get_pool()
        async with book.acquire() as conn:
            q = await conn.fetchrow("SELECT quality_score FROM books WHERE id = $1", row["id"])
        if q and q["quality_score"] < 50:
            try:
                from brainycat.deep_enrich import deep_enrich

                async with asyncio.timeout(30):
                    await deep_enrich(str(row["id"]))
            except Exception:
                pass

    if enriched:
        await log.ainfo("auto_enriched", count=enriched, batch=len(rows))


# ── Fingerprints + embeddings ─────────────────────────────────────────────
async def _fingerprint_loop() -> None:
    from brainycat.db import fetch_all
    from brainycat.embeddings import embed_book

    unembedded = await fetch_all("SELECT id FROM books WHERE embedding IS NULL AND description IS NOT NULL LIMIT 20")
    for r in unembedded:
        with contextlib.suppress(Exception):
            await embed_book(str(r["id"]))

    from brainycat.fingerprints import compute_all_fingerprints, find_duplicates_by_content

    # Only fingerprint books without ISBN (ISBN is sufficient for dedup)
    result = await compute_all_fingerprints(batch_size=10)
    if result["computed"] > 0:
        await log.ainfo("fingerprints", **result)

    if result.get("pending", 0) == 0:
        dupes = await find_duplicates_by_content(batch_size=20)
        if dupes["new_matches"] > 0:
            await log.ainfo("dupes_found", **dupes)


# ── Format stacking ──────────────────────────────────────────────────────
async def _format_stack_loop() -> None:
    from brainycat.format_stack import auto_stack_cycle
    from brainycat.series_detect import detect_series

    result = await auto_stack_cycle(limit=5)
    if result.get("stacked"):
        await log.ainfo("format_stacked", **result)
    await detect_series(limit=20)

    # Index content for full-text search
    from brainycat.search_index import index_batch
    await index_batch(limit=10)


# ── Title cleanup + genre classification (with rate limiting) ─────────────
async def _title_cleanup_loop() -> None:
    from brainycat.title_cleanup import run_title_cleanup_cycle

    result = await run_title_cleanup_cycle()
    isbn_found = result.get("isbn_from_filename", {}).get("found", 0)
    titles_fixed = result.get("api_title_fix", {}).get("fixed", 0)

    # Classify untagged books via Google Books (rate-limited)
    from brainycat.db import execute, fetch_one, get_pool
    from brainycat.http_client import get_client
    from brainycat.rate_limit import rate_limiter

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        untagged = await conn.fetch("""
            SELECT b.id, b.isbn FROM books b
            WHERE b.isbn IS NOT NULL AND length(b.isbn) >= 10
              AND NOT EXISTS (SELECT 1 FROM books_tags bt WHERE bt.book_id = b.id)
            LIMIT 5 FOR UPDATE SKIP LOCKED
        """)
        for row in untagged:
            await conn.execute("UPDATE books SET updated_at = now() WHERE id = $1", row["id"])

    genres_added = 0
    for row in untagged:
        try:
            await rate_limiter.wait("google")
            c = get_client()
            async with asyncio.timeout(10):
                from brainycat.config import settings as _cfg

                _gk = f"&key={_cfg.google_books_api_key}" if _cfg.google_books_api_key else ""
                resp = await c.get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{row['isbn']}&maxResults=1{_gk}")
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
            elif resp.status_code == 429:
                await rate_limiter.record_failure("google")
                break  # stop hammering
        except TimeoutError:
            pass
        except Exception:
            pass

    # Auto-detect series from title patterns
    try:
        from brainycat.series_detect import detect_series

        series_result = await detect_series(limit=20)
    except Exception:
        series_result = {}

    if isbn_found or titles_fixed or genres_added or series_result.get("detected"):
        await log.ainfo(
            "title_cleanup",
            isbn_found=isbn_found,
            titles_fixed=titles_fixed,
            genres_added=genres_added,
            series_detected=series_result.get("detected", 0),
        )


async def _split_pdf_chunk(pdf_path: str, max_bytes: int) -> str | None:
    """Split a large PDF into a chunk under max_bytes. Returns temp file path."""
    import os
    import tempfile

    import fitz

    try:
        src = fitz.open(pdf_path)
        total_pages = len(src)
        file_size = os.path.getsize(pdf_path)
        bytes_per_page = file_size / max(total_pages, 1)
        pages_per_chunk = max(1, int(max_bytes / bytes_per_page))

        # Take the first N pages that fit under the limit
        dst = fitz.open()
        dst.insert_pdf(src, from_page=0, to_page=min(pages_per_chunk, total_pages) - 1)

        tmp = tempfile.mktemp(suffix=".pdf")
        dst.save(tmp)
        dst.close()
        src.close()

        # Verify it's under the limit, shrink if needed
        if os.path.getsize(tmp) > max_bytes:
            os.unlink(tmp)
            src = fitz.open(pdf_path)
            dst = fitz.open()
            dst.insert_pdf(src, from_page=0, to_page=max(1, pages_per_chunk // 2) - 1)
            dst.save(tmp)
            dst.close()
            src.close()

        return tmp
    except Exception:
        return None


# ── OCR polling + submission ──────────────────────────────────────────────
async def _ocr_loop() -> None:
    from brainycat.config import settings
    from brainycat.db import execute, fetch_all, fetch_one
    from brainycat.http_client import get_client

    intello_url = settings.heavy_url.rstrip("/")
    client = get_client()

    # 0. Check Intello health before doing anything
    try:
        async with asyncio.timeout(5):
            health = await client.get(f"{intello_url}/api/health")
        if health.status_code == 200 and not health.json().get("healthy", False):
            await log.awarning("intello_unhealthy")
            return
    except Exception:
        return  # Intello unreachable, skip this cycle

    # 0b. Cache OCR capabilities (languages supported)
    ocr_langs = set()
    try:
        caps = await client.get(f"{intello_url}/api/v1/ocr/capabilities", timeout=5)
        if caps.status_code == 200:
            ocr_langs = set(caps.json().get("languages", []))
    except Exception:
        pass

    # 1. Poll pending OCR jobs
    pending = await fetch_all("SELECT id, book_id, remote_job_id FROM async_jobs WHERE job_type = 'ocr' AND status = 'submitted' LIMIT 5")
    for job in pending:
        try:
            async with asyncio.timeout(15):
                resp = await client.get(f"{intello_url}/api/v1/ocr/jobs/{job['remote_job_id']}")
            if resp.status_code != 200:
                continue
            data = resp.json()
            status = data.get("status", "unknown")
            if status == "complete":
                await execute("UPDATE async_jobs SET status = 'complete' WHERE id = $1", job["id"])
                if data.get("result_path"):
                    async with asyncio.timeout(120):
                        dl = await client.get(f"{intello_url}/api/v1/ocr/jobs/{job['remote_job_id']}/result")
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
        except TimeoutError:
            pass
        except Exception:
            pass

    # 2. Submit next if queue empty
    active = await fetch_one("SELECT id FROM async_jobs WHERE job_type = 'ocr' AND status = 'submitted' LIMIT 1")
    if not active:
        candidate = await fetch_one("""
            SELECT b.id, bf.file_path, b.language FROM books b
            JOIN book_files bf ON bf.book_id = b.id AND bf.format = 'pdf' AND bf.file_size BETWEEN 500000 AND 30000000
            WHERE NOT EXISTS (SELECT 1 FROM async_jobs aj WHERE aj.book_id = b.id AND aj.job_type = 'ocr')
            ORDER BY bf.file_size DESC LIMIT 1
        """)
        if candidate:
            import os
            import uuid

            if os.path.isfile(candidate["file_path"]):
                lang = (candidate["language"] or "eng")[:3]
                if ocr_langs and lang not in ocr_langs:
                    lang = "eng"  # fallback if language not supported
                try:
                    async with asyncio.timeout(60):
                        with open(candidate["file_path"], "rb") as f:
                            resp = await client.post(
                                f"{intello_url}/api/v1/ocr/jobs",
                                files={"file": ("book.pdf", f, "application/pdf")},
                                data={"language": lang, "output": "hybrid"},
                            )
                    if resp.status_code == 200:
                        remote_id = resp.json().get("job_id", "")
                        await execute(
                            "INSERT INTO async_jobs (id, book_id, job_type, remote_job_id, status) VALUES ($1, $2, 'ocr', $3, 'submitted')",
                            uuid.uuid4(),
                            candidate["id"],
                            remote_id,
                        )
                        await log.ainfo("ocr_submitted", book_id=str(candidate["id"]))
                except TimeoutError:
                    await log.awarning("ocr_submit_timeout")


async def _watcher_loop() -> None:
    """Check incoming folder for new files."""
    import os

    from brainycat.config import settings
    from brainycat.watcher import ALLOWED_EXT, IGNORE_EXT, _import_file

    incoming = settings.incoming_dir
    if not os.path.isdir(incoming):
        return

    for entry in os.scandir(incoming):
        if entry.is_file():
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in IGNORE_EXT or entry.name.startswith(".") or ext not in ALLOWED_EXT:
                continue
            # Check file is stable (not still being written)
            size1 = entry.stat().st_size
            await asyncio.sleep(2)
            size2 = os.path.getsize(entry.path) if os.path.exists(entry.path) else 0
            if size1 == size2 and size1 > 0:
                await _import_file(entry.path)
