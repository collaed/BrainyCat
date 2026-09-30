"""OL Works API enrichment — fetch description + rating for local-hit books.

Uses the work_key from the local SQLite dump to make direct GET requests
to /works/{key}.json — no search needed, surgical and rate-limit-friendly.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client


async def enrich_batch(batch_size: int = 10) -> dict[str, Any]:
    """Fetch descriptions from OL Works API for books that have a local hit."""

    # Find local-hit books missing description, that have an ISBN we can look up
    rows = await fetch_all("""
        SELECT b.id, b.isbn, b.title FROM books b
        WHERE b.extra_metadata->>'local_enriched' = 'true'
          AND (b.description IS NULL OR b.description = '')
          AND NOT (b.extra_metadata ? 'ol_works_tried')
          AND b.isbn IS NOT NULL
          AND b.identity_status != 'locked'
        ORDER BY b.quality_score ASC
        LIMIT $1
    """, batch_size)

    if not rows:
        return {"enriched": 0, "status": "complete"}

    from brainycat.ol_local import lookup_isbn

    enriched = 0
    for row in rows:
        isbn = row["isbn"].strip().replace("-", "")
        local = lookup_isbn(isbn)
        work_key = local.get("work_key") if local else None

        if not work_key:
            await _mark_tried(row["id"], None)
            continue

        # Direct GET — no search, minimal rate-limit impact
        # Simple 1s throttle between requests
        await asyncio.sleep(1)
        try:
            client = get_client()
            resp = await client.get(f"https://openlibrary.org{work_key}.json", timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                desc = data.get("description")
                if isinstance(desc, dict):
                    desc = desc.get("value")

                # Get ratings from ratings endpoint
                rating = None
                try:
                    r2 = await client.get(f"https://openlibrary.org{work_key}/ratings.json", timeout=5)
                    if r2.status_code == 200:
                        rating = r2.json().get("summary", {}).get("average")
                except Exception:
                    pass

                subjects = data.get("subjects", [])[:15]

                if desc:
                    await execute(
                        "UPDATE books SET description = $1, updated_at = now() WHERE id = $2",
                        desc[:5000], row["id"],
                    )
                    enriched += 1

                # Store subjects as tags
                for subj in subjects[:8]:
                    if subj and len(subj) > 2:
                        await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", subj[:50])
                        tag = await fetch_one("SELECT id FROM tags WHERE name = $1", subj[:50])
                        if tag:
                            await execute(
                                "INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                row["id"], tag["id"],
                            )

                await _mark_tried(row["id"], {
                    "description": bool(desc),
                    "rating": rating,
                    "subjects": len(subjects),
                })

                # Recompute quality score
                if desc or subjects:
                    from brainycat.metadata import recompute_quality
                    await recompute_quality(str(row["id"]))

                # Store rating in extra_metadata
                if rating:
                    await execute(
                        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{ol_rating}', $1::jsonb) WHERE id = $2",
                        json.dumps(rating), row["id"],
                    )

            elif resp.status_code == 429:
                await asyncio.sleep(60)  # simple backoff on rate limit
                break
            elif resp.status_code == 404:
                await _mark_tried(row["id"], {"not_found": True})
            else:
                await _mark_tried(row["id"], None)
        except Exception:
            await asyncio.sleep(10)
            break

    return {"enriched": enriched, "batch": len(rows)}


async def _mark_tried(book_id: UUID, result: Any) -> None:
    """Record that OL Works lookup was attempted for a book (so `enrich_batch`'s query skips it
    next cycle) — internal helper, only called from `enrich_batch` in this file."""
    await execute(
        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{ol_works_tried}', $1::jsonb) WHERE id = $2",
        json.dumps(result if result else True), book_id,
    )
