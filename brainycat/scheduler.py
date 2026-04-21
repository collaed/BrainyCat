"""Background scheduler — periodic enrichment, fingerprinting, duplicate detection."""

from __future__ import annotations

import asyncio

from brainycat.logging import log


async def start_scheduler() -> None:
    """Start background tasks."""
    asyncio.create_task(_enrichment_loop())  # noqa: RUF006
    asyncio.create_task(_fingerprint_loop())  # noqa: RUF006


async def _enrichment_loop() -> None:
    """Continuously enrich books with low quality scores."""
    await asyncio.sleep(30)
    while True:
        try:
            from brainycat.db import fetch_one
            from brainycat.metadata import enrich_book

            row = await fetch_one("SELECT id, title FROM books WHERE quality_score < 50 ORDER BY quality_score ASC, updated_at ASC LIMIT 1")
            if row:
                result = await enrich_book(str(row["id"]))
                if result.get("enriched"):
                    await log.ainfo("auto_enriched", title=row["title"], score=result.get("quality_score"))
        except Exception as e:
            await log.awarning("enrichment_error", error=str(e))
        await asyncio.sleep(10)


async def _fingerprint_loop() -> None:
    """Compute fingerprints and find duplicates in background."""
    await asyncio.sleep(60)
    while True:
        try:
            from brainycat.fingerprints import compute_all_fingerprints, find_duplicates_by_content

            # Compute fingerprints for 10 books at a time
            result = await compute_all_fingerprints(batch_size=10)
            if result["computed"] > 0:
                await log.ainfo("fingerprints_computed", **result)

            # Compare for duplicates
            if result.get("pending", 0) == 0:
                dupes = await find_duplicates_by_content(batch_size=20)
                if dupes["new_matches"] > 0:
                    await log.ainfo("duplicates_found", **dupes)
        except Exception as e:
            await log.awarning("fingerprint_error", error=str(e))
        await asyncio.sleep(30)
