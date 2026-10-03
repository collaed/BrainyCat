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
        # API-bound (network wait, don't block each other)
        ("enrichment", _enrichment_loop, 10),
        ("google_books", _google_books_loop, 20),
        ("covers", _cover_loop, 5),
        ("title_cleanup", _title_cleanup_loop, 90),
        ("ocr", _ocr_loop, 120),
        # Local-only (no network, fast)
        ("fast_local_isbn", _fast_local_isbn_loop, 2),
        ("fast_local_title", _fast_local_title_loop, 5),
        # ISBN extraction (dedicated worker thread — starts once, loops internally)
        ("isbn_extract", _isbn_extract_loop, 3600),
        ("ol_works", _ol_works_loop, 3),
        # Disk/mixed
        ("fingerprint", _fingerprint_loop, 20),
        ("format_stack", _format_stack_loop, 300),
        # NOTE: incipit_match removed from the schedule — brainycat/incipit_match.py is a 5-line stub
        # (it returned zero counts, i.e. silent false "success" every 600s). The real extraction
        # helpers in brainycat/incipit.py are kept; re-add the loop once incipit_match is implemented.
        # Housekeeping
        ("log_retention", _log_retention_loop, 86400),
        # Re-enabled: these two call REAL modules (metadata_validator.validate_batch — 173 lines;
        # confidence.compute_batch — 324 lines), verified to do actual work.
        ("validation", _validation_loop, 30),
        ("confidence", _confidence_loop, 60),
        # NOT scheduled: cover_phash and ocr_copyright are still 5-line stubs that return zero counts.
        # Scheduling them would make a job report success for work it didn't do (against the CLAUDE.md
        # convention) and show green on the M10 heartbeat. Their stub functions now raise
        # NotImplementedError so any accidental call is surfaced, not silently "successful". Re-add
        # them here once cover_phash.py / ocr_copyright.py are implemented. See docs/known-issues.md.
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
    """Runs every 10s. Locks a batch of up to 6 low-quality/not-yet-locked books, enriches them
    in parallel via `metadata.enrich_book`, fires off post-processing, and deep-enriches any that
    are still below quality 50 afterward. Registered in `start_scheduler`'s `loops` list."""
    from brainycat import db
    from brainycat.db import get_pool
    from brainycat.metadata import enrich_book

    pool = await get_pool()
    # Step 1: Find least-tried books (no lock — aggregates not allowed with FOR UPDATE)
    candidates = await db.fetch_all(
        "SELECT b.id, b.title FROM books b "
        "LEFT JOIN (SELECT book_id, count(*) as cnt FROM enrichment_log GROUP BY book_id) a ON a.book_id = b.id "
        "LEFT JOIN (SELECT book_id, max(created_at) as last_try FROM enrichment_log GROUP BY book_id) lt ON lt.book_id = b.id "
        "WHERE b.quality_score < 95 AND b.identity_status != 'locked' "
        "AND (lt.last_try IS NULL OR lt.last_try < now() - interval '7 days' * (COALESCE(a.cnt, 0) / 10.0 + 1)) "
        "ORDER BY b.quality_score ASC, COALESCE(a.cnt, 0) ASC, b.updated_at ASC "
        "LIMIT 10"
    )
    # Step 2: Lock 6 one-by-one (FOR UPDATE SKIP LOCKED per row)
    rows = []
    async with pool.acquire() as conn, conn.transaction():
        for c in candidates:
            if len(rows) >= 6:
                break
            locked = await conn.fetchrow("SELECT id, title FROM books WHERE id = $1 FOR UPDATE SKIP LOCKED", c["id"])
            if locked:
                await conn.execute("UPDATE books SET updated_at = now() WHERE id = $1", locked["id"])
                rows.append(locked)

    # Enrich all locked books in parallel (not sequentially)
    async def _enrich_one(row):
        """Enrich a single locked book with a 20s timeout, returning 1 if enrichment succeeded else 0.
        Internal helper used only within `_enrichment_loop`, run concurrently via `asyncio.gather`."""
        try:
            async with asyncio.timeout(20):
                result = await enrich_book(str(row["id"]), skip_postprocess=True)
                return 1 if result.get("enriched") else 0
        except TimeoutError:
            await log.awarning("enrichment_timeout", book_id=str(row["id"]))
        except Exception:
            pass
        return 0

    results = await asyncio.gather(*[_enrich_one(r) for r in rows])
    enriched = sum(results)

    # Post-processing (covers, writeback, organize) — fire and forget, no timeout pressure
    for row in rows:
        asyncio.create_task(_postprocess(str(row["id"])))

    # Stage 2: Deep enrich for books still below 50 after standard enrichment
    for row in rows:
        book = await get_pool()
        async with book.acquire() as conn:
            q = await conn.fetchrow("SELECT quality_score FROM books WHERE id = $1", row["id"])
        if q and q["quality_score"] < 50:
            try:
                from brainycat.deep_enrich import deep_enrich

                async with asyncio.timeout(45):
                    await deep_enrich(str(row["id"]))
            except Exception:
                pass

    if enriched:
        await log.ainfo("auto_enriched", count=enriched, batch=len(rows))


async def _postprocess(book_id: str) -> None:
    """Deferred post-processing: cover download, writeback, organize. Non-critical."""
    try:
        from brainycat.metadata import postprocess_book
        async with asyncio.timeout(90):
            await postprocess_book(book_id)
    except Exception:
        pass


# ── Google Books dedicated loop (independent of main enrichment) ──────────
async def _google_books_loop() -> None:
    """Fast Google Books enrichment — runs at ~1 req/s with API key, independent of other sources."""
    from brainycat.config import settings

    if not settings.google_books_api_key:
        return  # no key, skip dedicated loop — main enrichment handles it

    from brainycat.sources import google_books

    # Skip if both key and proxy are exhausted (avoid wasting log entries)
    import time
    now = time.monotonic()
    if now < google_books._key_exhausted_until and now < google_books._anon_exhausted_until:
        return

    from brainycat import db
    from brainycat.relevance_guard import is_relevant

    # Find books not yet hit by google_books (skip audio-only and very short titles)
    row = await db.fetch_one(
        "SELECT b.id, b.title, b.isbn FROM books b "
        "JOIN book_files bf ON bf.book_id = b.id "
        "WHERE b.quality_score < 95 AND length(b.title) > 3 "
        "AND bf.format IN ('epub','pdf','mobi','azw3','fb2','djvu','txt') "
        "AND NOT EXISTS (SELECT 1 FROM enrichment_log el WHERE el.book_id = b.id AND el.method = 'google_books') "
        "ORDER BY (b.isbn IS NOT NULL) DESC, b.quality_score ASC LIMIT 1"
    )
    if not row:
        return

    title = row["title"]
    if not title:
        # Can't search without a title, mark as attempted
        await db.execute(
            "INSERT INTO enrichment_log (book_id, method, success) VALUES ($1, 'google_books', false)",
            row["id"],
        )
        return
    isbn = row["isbn"] if "isbn" in row.keys() else None
    result = await google_books.search(title=title, isbn=isbn)

    success = False
    if result and is_relevant(title or "", result.get("title", "") or "", result.get("isbn", "") or "", isbn or ""):
        # Merge fields directly on books table
        updates = []
        params = []
        idx = 1
        for field in ("description", "cover_url"):
            val = result.get(field)
            if val:
                col = "cover_path" if field == "cover_url" else field
                existing = await db.fetch_one(f"SELECT {col} FROM books WHERE id = $1", row["id"])
                if existing and not existing[col]:
                    idx += 1
                    updates.append(f"{col} = ${idx}")
                    params.append(val)
        if result.get("pubdate") and not (await db.fetch_one("SELECT pubdate FROM books WHERE id = $1", row["id"]))["pubdate"]:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(result["pubdate"].replace("Z", "+00:00")) if "T" in result["pubdate"] else datetime.strptime(result["pubdate"][:10], "%Y-%m-%d")
                idx += 1
                updates.append(f"pubdate = ${idx}")
                params.append(dt)
            except (ValueError, TypeError):
                pass
        if result.get("isbn") and not isbn:
            idx += 1
            updates.append(f"isbn = ${idx}")
            params.append(result["isbn"])
        if updates:
            await db.execute(
                f"UPDATE books SET {', '.join(updates)}, updated_at = now() WHERE id = $1",
                row["id"], *params
            )
        success = True

    await db.execute(
        "INSERT INTO enrichment_log (book_id, method, success) VALUES ($1, 'google_books', $2)",
        row["id"], success,
    )


# ── Fingerprints + embeddings ─────────────────────────────────────────────
async def _fingerprint_loop() -> None:
    """Compute content fingerprints for un-fingerprinted books, then compare for content-level
    duplicates once a batch is caught up. (Previously named _text_profiler_loop and routed through
    a brainycat.text_profiler.process_batch() that was never implemented — see docs/known-issues.md
    — which meant this loop, and the two real functions below, never actually ran.)"""
    from brainycat.fingerprints import compute_all_fingerprints, find_duplicates_by_content

    result = await compute_all_fingerprints(batch_size=20)
    if result.get("computed", 0) > 0:
        await log.ainfo("fingerprints_computed", **result)

    # Run dedup comparison periodically (when no new files to fingerprint)
    if result.get("pending", 0) == 0:
        dupes = await find_duplicates_by_content(batch_size=20)
        if dupes["new_matches"] > 0:
            await log.ainfo("dupes_found", **dupes)



# ── Cover fetching (fills gaps for books with ISBN but no cover) ──────────
async def _cover_loop() -> None:
    """Fetch covers from Apple Books / Bookcover API for books missing covers."""
    from brainycat import db
    from brainycat.http_client import get_client
    from brainycat.sources.covers import apple_cover, bookcover_api

    row = await db.fetch_one(
        "SELECT id, isbn, title FROM books "
        "WHERE (cover_path IS NULL OR cover_path = '') AND isbn IS NOT NULL AND isbn != '' "
        "ORDER BY quality_score DESC LIMIT 1"
    )
    if not row:
        return

    isbn = row["isbn"]
    cover_url = await apple_cover(isbn) or await bookcover_api(isbn)
    if not cover_url:
        # Try Open Library cover
        cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

    if cover_url:
        try:
            client = get_client()
            resp = await client.get(cover_url, timeout=15, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                import os
                cover_dir = "/data/covers"
                os.makedirs(cover_dir, exist_ok=True)
                ext = ".jpg"
                path = f"{cover_dir}/{row['id']}{ext}"
                with open(path, "wb") as f:
                    f.write(resp.content)
                await db.execute("UPDATE books SET cover_path = $1, updated_at = now() WHERE id = $2", path, row["id"])
                return
        except Exception:
            pass

    # Mark as attempted so we don't retry endlessly (set empty placeholder)
    await db.execute("UPDATE books SET cover_path = 'none', updated_at = now() WHERE id = $1", row["id"])

# ── Format stacking ──────────────────────────────────────────────────────

# ── Metadata validation (cross-check enrichment vs actual content) ────────
async def _validation_loop() -> None:
    """Validate metadata against book content. Low priority, runs on profiled books."""
    from brainycat.metadata_validator import validate_batch

    result = await validate_batch(batch_size=10)
    if result.get("validated", 0) > 0:
        await log.ainfo("validation_run", **result)

async def _format_stack_loop() -> None:
    """Runs every 300s (5 min). Auto-stacks matching formats of the same book, detects series from
    titles, runs dedup merge, and (if enabled) FTS indexing and email import. Registered in
    `start_scheduler`'s `loops` list."""
    from brainycat.series_detect import detect_series

    try:
        from brainycat.format_stack import auto_stack_cycle
        result = await auto_stack_cycle(limit=5)
        if result.get("stacked"):
            await log.ainfo("format_stacked", **result)
    except Exception:
        pass  # Don't let format_stack kill the whole loop

    await detect_series(limit=20)

    # Dedup: verify and merge confirmed duplicates
    try:
        from brainycat.dedup_engine import auto_dedup_cycle
        dedup = await auto_dedup_cycle(limit=5)
        if dedup.get("merged"):
            await log.ainfo("dedup_merged", **dedup)
    except Exception:
        pass

    # FTS indexing (independent of format_stack success)
    from brainycat.config import settings
    if getattr(settings, 'enable_fts', False):
        from brainycat.search_index import index_batch
        await index_batch(limit=20)

    # Email consumption
    if getattr(settings, 'enable_email_import', False):
        from brainycat.email_consume import check_email_inbox
        await check_email_inbox()


# ── Title cleanup + genre classification (with rate limiting) ─────────────
async def _title_cleanup_loop() -> None:
    """Runs every 90s. Runs the title-cleanup cycle (ISBN-from-filename, API title fixes),
    classifies a few untagged books via Google Books, and auto-detects series from titles.
    Registered in `start_scheduler`'s `loops` list."""
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
    """Runs every 120s. Checks the Intello OCR service's health, polls pending OCR jobs for
    completion (downloading and storing finished results), then submits the next eligible
    unprocessed PDF for OCR if the queue is empty. Registered in `start_scheduler`'s `loops` list."""
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


# ── Fast local lookup (no network, bulk ISBN/title matching) ──────────────
async def _fast_local_isbn_loop() -> None:
    """Runs every 2s. Runs a batch of the local (no-network) ISBN lookup pass. Registered in
    `start_scheduler`'s `loops` list."""
    from brainycat.fast_local import fast_local_pass
    result = await fast_local_pass(batch_size=100)
    if result.get("enriched", 0) > 0:
        await log.ainfo("fast_local_isbn", **result)


async def _fast_local_title_loop() -> None:
    """Runs every 5s. Runs a batch of the local (no-network) title-matching pass. Registered in
    `start_scheduler`'s `loops` list."""
    from brainycat.fast_local import fast_title_pass
    result = await fast_title_pass(batch_size=50)
    if result.get("found", 0) > 0:
        await log.ainfo("fast_local_title", **result)


# ── ISBN extraction from book content (dedicated thread) ──────────────────
_isbn_thread_started = False
_isbn_pick_lock = None  # initialized on first use


async def _isbn_extract_loop() -> None:
    """Start the ISBN extraction worker threads (once). They run independently."""
    global _isbn_thread_started, _isbn_pick_lock
    if _isbn_thread_started:
        return
    _isbn_thread_started = True
    import threading
    _isbn_pick_lock = threading.Lock()
    for i in range(2):
        t = threading.Thread(target=_isbn_worker, args=(i,), daemon=True, name=f"isbn_extract_{i}")
        t.start()
    await log.ainfo("isbn_workers_started", threads=2)


def _isbn_worker(worker_id: int) -> None:
    """Dedicated thread: picks one book at a time, extracts ISBN, writes result. Loops forever."""
    import json
    import os
    import time
    import zipfile

    import psycopg2
    import psycopg2.extras

    from brainycat.config import settings
    from brainycat.isbn import extract_from_filename, extract_from_opf, extract_from_pdf_metadata, extract_from_text

    conn = psycopg2.connect(settings.database_url)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    while True:
        try:
            # Synchronized: only one thread picks at a time
            with _isbn_pick_lock:
                # books.original_filename doesn't exist — book_files.file_name is the real source
                # (see docs/known-issues.md).
                cur.execute("""
                    SELECT b.id, bf.file_name AS original_filename, bf.file_path, bf.format
                    FROM books b
                    JOIN book_files bf ON bf.book_id = b.id
                    WHERE (b.isbn IS NULL OR b.isbn = '')
                      AND bf.format IN ('epub','pdf','mobi','azw3')
                      AND NOT (b.extra_metadata ? 'isbn_extract_tried')
                    ORDER BY random()
                    LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    # Mark immediately so the other thread won't pick it
                    cur.execute(
                        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{isbn_extract_tried}', 'true'::jsonb) WHERE id = %s",
                        (row["id"],),
                    )

            if not row:
                time.sleep(60)
                continue

            book_id = row["id"]
            file_path = row["file_path"]
            fmt = row["format"]
            orig_filename = row["original_filename"]

            isbn = None
            extra: dict = {}

            # Phase 1: OPF metadata (epub only)
            if fmt == "epub" and os.path.isfile(file_path):
                opf = extract_from_opf(file_path)
                isbn = opf.get("isbn")
                extra.update({k: v for k, v in opf.items() if k != "identifiers"})

            # Phase 2: PDF metadata
            if not isbn and fmt == "pdf" and os.path.isfile(file_path):
                isbn = extract_from_pdf_metadata(file_path)

            # Phase 3: Filename
            if not isbn and orig_filename:
                isbn = extract_from_filename(orig_filename)

            # Phase 4: Full text scan
            if not isbn and os.path.isfile(file_path):
                text = ""
                if fmt == "epub":
                    try:
                        with zipfile.ZipFile(file_path) as zf:
                            htmls = sorted(n for n in zf.namelist() if n.endswith((".xhtml", ".html")))
                            for h in htmls[:15]:
                                text += zf.read(h).decode("utf-8", errors="ignore") + "\n"
                    except Exception:
                        pass
                elif fmt == "pdf":
                    try:
                        import fitz
                        doc = fitz.open(file_path)
                        for i in range(min(20, len(doc))):
                            text += doc[i].get_text() + "\n"
                        doc.close()
                    except Exception:
                        pass

                if text:
                    text_data = extract_from_text(text)
                    isbn = text_data.get("isbn") or text_data.get("isbn_10")
                    extra.update(text_data)

            # Write results
            if isbn:
                cur.execute("UPDATE books SET isbn = %s, updated_at = now() WHERE id = %s AND (isbn IS NULL OR isbn = '')", (isbn, book_id))
                cur.execute("INSERT INTO enrichment_log (book_id, method, success) VALUES (%s, 'isbn_extract', true)", (book_id,))

            # Store extracted metadata
            meta = {k: v for k, v in extra.items() if k not in ("ok", "isbn", "isbn_10") and v}
            if meta:
                cur.execute(
                    "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || %s::jsonb WHERE id = %s",
                    (json.dumps(meta), book_id),
                )

            time.sleep(0)  # yield to OS scheduler

        except Exception:
            time.sleep(10)


# ── OL Works API (description+rating for local-hit books) ─────────────────
async def _ol_works_loop() -> None:
    """Runs every 3s. Runs a batch of Open Library Works API enrichment (description/rating) for
    books with a local ISBN hit. Registered in `start_scheduler`'s `loops` list."""
    from brainycat.ol_works import enrich_batch
    result = await enrich_batch(batch_size=10)
    if result.get("enriched", 0) > 0 or result.get("skipped"):
        await log.ainfo("ol_works", **result)


# ── OCR Copyright Page (extract ISBN from first pages) ────────────────────
async def _ocr_copyright_loop() -> None:
    """Would run a batch of copyright-page OCR to extract ISBNs. Not currently registered in
    `start_scheduler`'s `loops` list — `brainycat.ocr_copyright` was never implemented (see
    docs/known-issues.md)."""
    from brainycat.ocr_copyright import process_batch
    result = await process_batch(batch_size=5)
    if result.get("isbn_found", 0) > 0:
        await log.ainfo("ocr_copyright", **result)


# ── Cover Perceptual Hash ─────────────────────────────────────────────────
async def _cover_phash_loop() -> None:
    """Would run a batch of cover perceptual-hashing. Not currently registered in
    `start_scheduler`'s `loops` list — `brainycat.cover_phash` was never implemented (see
    docs/known-issues.md)."""
    from brainycat.cover_phash import process_batch
    result = await process_batch(batch_size=20)
    if result.get("computed", 0) > 0:
        await log.ainfo("cover_phash", **result)


# ── Incipit Matching (periodic dedup via opening text) ────────────────────
async def _incipit_match_loop() -> None:
    """Runs every 600s (10 min). Runs a batch of dedup-via-opening-text matching and propagates
    ISBNs across matched groups. Registered in `start_scheduler`'s `loops` list."""
    from brainycat.incipit_match import find_incipit_matches
    result = await find_incipit_matches(batch_size=100)
    if result.get("isbn_propagated", 0) > 0 or result.get("groups", 0) > 0:
        await log.ainfo("incipit_match", **result)


# ── Confidence scoring ────────────────────────────────────────────────────
async def _confidence_loop() -> None:
    """Would run a batch of confidence scoring and recompute stale quality scores. Not currently
    registered in `start_scheduler`'s `loops` list — `brainycat.confidence` was never implemented
    (see docs/known-issues.md)."""
    from brainycat.confidence import compute_batch
    result = await compute_batch(batch_size=50)
    if result.get("computed", 0) > 0:
        await log.ainfo("confidence_scored", **result)

    # Recompute stale quality scores (books enriched locally but score not updated)
    from brainycat.db import fetch_all
    from brainycat.metadata import recompute_quality
    stale = await fetch_all("""
        SELECT id FROM books
        WHERE (extra_metadata ? 'local_enriched' OR extra_metadata ? 'ol_works_tried')
          AND quality_score < 30
        LIMIT 50
    """)
    for row in stale:
        await recompute_quality(str(row["id"]))


async def _watcher_loop() -> None:
    """Check incoming folder for new files."""
    import os

    from brainycat.config import settings
    from brainycat.watcher import ALLOWED_EXT, IGNORE_EXT, _import_file

    incoming = settings.incoming_dir
    if not os.path.isdir(incoming):
        return

    # First pass: group multi-file audiobooks and import as one
    try:
        from brainycat.audiobook_group import find_audio_groups, import_audio_group
        groups = find_audio_groups(incoming)
        for title, files in list(groups.items())[:3]:  # max 3 groups per cycle
            await import_audio_group(title, files)
    except Exception:
        pass

    # Second pass: individual files
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


async def _log_retention_loop() -> None:
    """Purge rows older than 30 days from the DB-backed log tables (enrichment_log, job_logs) —
    these grow one row per enrichment attempt per book and would otherwise accumulate forever."""
    from brainycat.db import execute

    await execute("DELETE FROM enrichment_log WHERE created_at < now() - interval '30 days'")
    await execute("DELETE FROM job_logs WHERE created_at < now() - interval '30 days'")
