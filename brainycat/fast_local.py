"""Fast local-only enrichment — bulk ISBN lookup against offline dumps.

Bypasses the full enrichment pipeline (no Intello, no covers, no writeback).
Just: ISBN → local DB → store metadata. Can process ~1000 books/min.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.logging import log


async def fast_local_pass(batch_size: int = 100) -> dict[str, Any]:
    """Bulk enrich books that have ISBN but haven't been locally matched yet."""
    from brainycat.ol_local import lookup_bnf, lookup_isbn

    rows = await fetch_all("""
        SELECT b.id, b.isbn, b.title, b.description, b.pubdate
        FROM books b
        WHERE b.isbn IS NOT NULL AND length(b.isbn) >= 10
          AND NOT (b.extra_metadata ? 'local_enriched')
        ORDER BY b.quality_score ASC
        LIMIT $1
    """, batch_size)

    if not rows:
        return {"status": "complete", "enriched": 0}

    enriched = 0
    for row in rows:
        isbn = row["isbn"].strip().replace("-", "")
        result = lookup_isbn(isbn) or lookup_bnf(isbn)

        if result:
            updates = []
            params: list[Any] = []
            idx = 0

            if result.get("publisher") and not await _has_publisher(row["id"]):
                await _add_publisher(row["id"], result["publisher"])

            if result.get("subjects"):
                for subj in result["subjects"][:5]:
                    if subj and len(subj) > 2:
                        await _add_tag(row["id"], subj)

            if result.get("year") and not row["pubdate"]:
                from datetime import datetime, timezone
                idx += 1
                updates.append(f"pubdate = ${idx}")
                params.append(datetime(result["year"], 1, 1, tzinfo=timezone.utc))

            if result.get("title") and not row["description"]:
                # Don't overwrite title, but store OL title for reference
                pass

            if result.get("cover_id") and not (await fetch_one("SELECT cover_path FROM books WHERE id = $1", row["id"]))["cover_path"]:
                idx += 1
                updates.append(f"cover_path = ${idx}")
                params.append(f"https://covers.openlibrary.org/b/id/{result['cover_id']}-L.jpg")

            # Mark as locally enriched
            idx += 1
            updates.append(f"extra_metadata = jsonb_set(COALESCE(extra_metadata, '{{}}'::jsonb), '{{local_enriched}}', ${idx}::jsonb)")
            params.append(json.dumps(True))

            if updates:
                idx += 1
                params.append(row["id"])
                await execute(f"UPDATE books SET {', '.join(updates)}, updated_at = now() WHERE id = ${idx}", *params)

            # Recompute quality score with new data
            from brainycat.metadata import recompute_quality
            await recompute_quality(str(row["id"]))

            enriched += 1
        else:
            # Mark as attempted so we don't retry
            await execute(
                "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{local_enriched}', 'false'::jsonb) WHERE id = $1",
                row["id"],
            )

    return {"enriched": enriched, "batch": len(rows)}


async def fast_title_pass(batch_size: int = 50) -> dict[str, Any]:
    """For books WITHOUT ISBN — try title lookup against local DB (3 tiers)."""
    from brainycat.ol_local import _get_conn, _normalize_title

    rows = await fetch_all("""
        SELECT b.id, b.title
        FROM books b
        WHERE (b.isbn IS NULL OR b.isbn = '')
          AND NOT (b.extra_metadata ? 'local_title_tried')
          AND length(b.title) > 5
        ORDER BY b.quality_score ASC
        LIMIT $1
    """, batch_size)

    if not rows:
        return {"status": "complete", "found": 0}

    conn = _get_conn()
    found = 0

    for row in rows:
        norm = _normalize_title(row["title"])
        if len(norm) < 4:
            await _mark_title_tried(row["id"], None)
            continue

        match = _fuzzy_local_match(conn, norm)

        # Second line: try BnF title match if OL didn't find anything
        if not match:
            from brainycat.ol_local import lookup_bnf_title
            match = lookup_bnf_title(row["title"])

        if match:
            isbn = match["isbn"]
            confidence = match["confidence"]
            await execute(
                "UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2 AND (isbn IS NULL OR isbn = '')",
                isbn, row["id"],
            )
            await execute(
                "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{local_title_tried}', $1::jsonb) WHERE id = $2",
                json.dumps({"isbn_from": match["method"], "confidence": confidence, "ol_key": match.get("ol_key")}),
                row["id"],
            )
            from brainycat.metadata import recompute_quality
            await recompute_quality(str(row["id"]))
            found += 1
        else:
            await _mark_title_tried(row["id"], None)

    return {"found": found, "batch": len(rows)}


def _fuzzy_local_match(conn, norm_title: str) -> dict[str, Any] | None:
    """3-tier fuzzy matching against local title_lookup DB.

    Tier 1: Prefix match (first 4 words) → 80% confidence
    Tier 2: Word-subset match (3+ shared words) → 60% confidence
    Tier 3: Trigram similarity (>0.5) → 40% confidence
    """
    words = norm_title.split()

    # Tier 1: Prefix match (first 4 significant words)
    if len(words) >= 3:
        prefix = " ".join(words[:4])
        rows = conn.execute(
            "SELECT isbn, ol_key, norm_title FROM title_lookup WHERE norm_title LIKE ? LIMIT 5",
            (prefix + "%",),
        ).fetchall()
        if rows:
            # Pick best: prefer exact-length match
            best = min(rows, key=lambda r: abs(len(r["norm_title"]) - len(norm_title)))
            return {"isbn": best["isbn"], "ol_key": best["ol_key"], "method": "prefix_match", "confidence": 0.8}

    # Tier 2: Word-subset (any 3+ word combo from title)
    if len(words) >= 3:
        # Try combinations of significant words (>3 chars)
        sig_words = [w for w in words if len(w) > 3][:6]
        if len(sig_words) >= 3:
            # Search for entries containing all significant words via LIKE
            pattern = "%".join(sig_words[:3])
            rows = conn.execute(
                "SELECT isbn, ol_key, norm_title FROM title_lookup WHERE norm_title LIKE ? LIMIT 10",
                ("%" + pattern + "%",),
            ).fetchall()
            if rows:
                # Score by word overlap
                best = None
                best_score = 0
                title_words = set(words)
                for r in rows:
                    r_words = set(r["norm_title"].split())
                    overlap = len(title_words & r_words)
                    score = overlap / max(len(title_words), len(r_words))
                    if score > best_score:
                        best_score = score
                        best = r
                if best and best_score >= 0.5:
                    return {"isbn": best["isbn"], "ol_key": best["ol_key"], "method": "word_subset", "confidence": 0.6}

    # Tier 3: Trigram similarity
    if len(norm_title) >= 8:
        # Generate trigrams from our title
        our_trigrams = set(norm_title[i:i+3] for i in range(len(norm_title) - 2))
        # Search by first 3 chars as prefix filter, then compute trigram sim
        prefix3 = norm_title[:3]
        rows = conn.execute(
            "SELECT isbn, ol_key, norm_title FROM title_lookup WHERE norm_title LIKE ? LIMIT 50",
            (prefix3 + "%",),
        ).fetchall()
        best = None
        best_sim = 0
        for r in rows:
            r_trigrams = set(r["norm_title"][i:i+3] for i in range(len(r["norm_title"]) - 2))
            if not r_trigrams:
                continue
            sim = len(our_trigrams & r_trigrams) / max(len(our_trigrams), len(r_trigrams))
            if sim > best_sim:
                best_sim = sim
                best = r
        if best and best_sim > 0.5:
            return {"isbn": best["isbn"], "ol_key": best["ol_key"], "method": "trigram", "confidence": 0.4}

    return None


async def _mark_title_tried(book_id, result) -> None:
    await execute(
        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{local_title_tried}', 'true'::jsonb) WHERE id = $1",
        book_id,
    )


async def _has_publisher(book_id: UUID) -> bool:
    r = await fetch_one("SELECT 1 FROM books_publishers WHERE book_id = $1", book_id)
    return r is not None


async def _add_publisher(book_id: UUID, name: str) -> None:
    await execute("INSERT INTO publishers (name) VALUES ($1) ON CONFLICT DO NOTHING", name)
    pub = await fetch_one("SELECT id FROM publishers WHERE name = $1", name)
    if pub:
        await execute("INSERT INTO books_publishers (book_id, publisher_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", book_id, pub["id"])


async def _add_tag(book_id: UUID, name: str) -> None:
    name = name.strip()[:50]
    await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", name)
    tag = await fetch_one("SELECT id FROM tags WHERE name = $1", name)
    if tag:
        await execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", book_id, tag["id"])
