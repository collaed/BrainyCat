"""Background scheduler — periodic enrichment, fingerprinting, duplicate detection."""

from __future__ import annotations

import asyncio

from brainycat.logging import log


async def start_scheduler() -> None:
    asyncio.create_task(_enrichment_loop())  # noqa: RUF006
    asyncio.create_task(_fingerprint_loop())  # noqa: RUF006
    asyncio.create_task(_title_cleanup_loop())  # noqa: RUF006
    await log.ainfo("scheduler_started")


async def _enrichment_loop() -> None:
    await asyncio.sleep(15)
    while True:
        try:
            from brainycat.db import fetch_all
            from brainycat.metadata import enrich_book

            rows = await fetch_all("SELECT id, title FROM books WHERE quality_score < 50 ORDER BY updated_at ASC LIMIT 3")
            enriched = 0
            for row in rows:
                result = await enrich_book(str(row["id"]))
                if result.get("enriched"):
                    enriched += 1
                # Mark as attempted even if no results (bump updated_at so we don't retry immediately)
                from brainycat.db import execute

                await execute("UPDATE books SET updated_at = now() WHERE id = $1", row["id"])
            if enriched:
                await log.ainfo("auto_enriched", count=enriched, batch=len(rows))
        except Exception as e:
            await log.awarning("enrichment_error", error=str(e))
        await asyncio.sleep(60)  # 60s between batches — adaptive rate limiter handles per-source delays


async def _fingerprint_loop() -> None:
    await asyncio.sleep(45)
    while True:
        try:
            # Generate embeddings for books without them
            from brainycat.embeddings import embed_all_books

            await embed_all_books(limit=20)

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
