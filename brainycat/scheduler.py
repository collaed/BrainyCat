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

            rows = await fetch_all("SELECT id, title FROM books WHERE quality_score < 50 ORDER BY updated_at ASC LIMIT 5")
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
        await asyncio.sleep(15)  # 15s between batches to respect API rate limits


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
            if isbn_found or titles_fixed:
                await log.ainfo("title_cleanup", isbn_found=isbn_found, titles_fixed=titles_fixed)
        except Exception as e:
            await log.awarning("title_cleanup_error", error=str(e))
        await asyncio.sleep(60)  # Every 60s
