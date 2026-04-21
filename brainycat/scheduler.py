"""Background scheduler — periodic enrichment, cover extraction, cleanup."""

from __future__ import annotations

import asyncio

from brainycat.db import fetch_one
from brainycat.logging import log


async def start_scheduler() -> None:
    """Start background tasks. Called from app lifespan."""
    asyncio.create_task(_enrichment_loop())  # noqa: RUF006


async def _enrichment_loop() -> None:
    """Continuously enrich books with low quality scores."""
    await asyncio.sleep(30)  # wait for app to stabilize
    while True:
        try:
            # Find a book needing enrichment (quality < 50, not enriched recently)
            row = await fetch_one("""
                SELECT id, title, isbn FROM books
                WHERE quality_score < 50
                ORDER BY quality_score ASC, updated_at ASC
                LIMIT 1
            """)
            if row:
                from brainycat.metadata import enrich_book

                result = await enrich_book(str(row["id"]))
                if result.get("enriched"):
                    await log.ainfo("auto_enriched", title=row["title"], score=result.get("quality_score"))
        except Exception as e:
            await log.awarning("enrichment_loop_error", error=str(e))

        await asyncio.sleep(10)  # every 10 seconds
