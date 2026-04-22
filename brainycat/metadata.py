"""Metadata enrichment from external sources."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one
from brainycat.logging import log
from brainycat.sources import google_books, gutendex, hardcover, loc, oclc, open_library


async def enrich_book(book_id: str) -> dict[str, Any]:
    """Fetch metadata from all sources and merge into the book record."""
    row = await fetch_one("SELECT * FROM books WHERE id = $1", UUID(book_id))
    if not row:
        return {"error": "not found"}

    title = row["title"]
    isbn = row["isbn"]

    # Query sources in parallel-ish
    results = []
    for source_fn in [google_books.search, open_library.search, oclc.search, loc.search, hardcover.search, gutendex.search]:
        source_name = source_fn.__module__.split(".")[-1]
        try:
            r = await source_fn(title=title, isbn=isbn)
            if r:
                results.append(r)
                await execute(
                    "INSERT INTO enrichment_log (book_id, method, success, details) VALUES ($1, $2, true, $3::jsonb)",
                    UUID(book_id),
                    source_name,
                    json.dumps({"fields": list(r.keys())}),
                )
            else:
                await execute(
                    "INSERT INTO enrichment_log (book_id, method, success) VALUES ($1, $2, false)",
                    UUID(book_id),
                    source_name,
                )
        except Exception as e:
            await log.awarning("enrichment_source_failed", source=source_name, error=str(e))

    if not results:
        return {"enriched": False, "reason": "no results"}

    # Merge: pick best value per field
    merged: dict[str, Any] = {}
    for field in ["title", "description", "isbn", "cover_url", "language", "publisher", "pubdate", "genres"]:
        for r in results:
            val = r.get(field)
            if val and not merged.get(field):
                merged[field] = val

    # Update book
    sets, vals = [], []
    idx = 1
    for field in ["description", "isbn"]:
        if merged.get(field) and not row[field]:
            sets.append(f"{field} = ${idx}")
            vals.append(merged[field])
            idx += 1

    if sets:
        vals.append(UUID(book_id))
        await execute(f"UPDATE books SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)

    # Download cover
    if merged.get("cover_url") and not row["cover_path"]:
        try:
            import os

            import httpx

            from brainycat.storage import book_dir

            async with httpx.AsyncClient() as client:
                resp = await client.get(merged["cover_url"], timeout=15)
                if resp.status_code == 200:
                    cover_path = os.path.join(book_dir(book_id), "cover.jpg")
                    with open(cover_path, "wb") as f:
                        f.write(resp.content)
                    await execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, UUID(book_id))
        except Exception:
            pass

    # Update quality score
    score = _compute_quality(book_id, row, merged)
    await execute("UPDATE books SET quality_score = $1 WHERE id = $2", score, UUID(book_id))

    return {"enriched": True, "quality_score": score, "sources": len(results)}


def _compute_quality(book_id: str, row: Any, merged: dict[str, Any]) -> int:
    """Weighted completeness score 0-100."""
    weights = {
        "title": 10,
        "description": 15,
        "isbn": 10,
        "cover_path": 15,
        "language": 5,
        "publisher": 5,
        "pubdate": 5,
    }
    score = 0
    # Author worth 15 — check separately
    score += 15  # assume author present from upload
    # Genres worth 10
    if merged.get("genres"):
        score += 10
    for field, weight in weights.items():
        val = merged.get(field) or (row[field] if field in dict(row) else None)
        if val:
            score += weight
    return min(score, 100)


async def classify_genre_via_llm(book_id: str) -> dict[str, Any]:
    """Use LLM to classify a book's genre from its title + description + text sample."""
    row = await fetch_one("SELECT title, description FROM books WHERE id = $1", UUID(book_id))
    if not row:
        return {"error": "not found"}

    title = row["title"] or ""
    desc = (row["description"] or "")[:500]

    # Try to get a text sample from the book
    sample = ""
    file_row = await fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 AND format IN ('epub','pdf') LIMIT 1", UUID(book_id)
    )
    if file_row and os.path.isfile(file_row["file_path"]):
        try:
            from brainycat.fingerprints import _extract_full_text

            text = _extract_full_text(file_row["file_path"], file_row["format"])
            if len(text) > 2000:
                mid = len(text) // 2
                sample = text[1000:3000]  # first 2KB after intro
                sample += "\n...\n" + text[mid : mid + 2000]  # 2KB from middle
        except Exception:
            pass

    prompt = f"""Classify this book into Thema subject categories. Return JSON only.

Title: {title}
Description: {desc[:300]}
Text sample: {sample[:3000]}

Return: {{"thema_code": "XX", "thema_label": "...", "fiction": true/false, "genre": "...", "subgenre": "...", "language": "en/fr/de/...", "confidence": 0.0-1.0}}"""

    try:
        import httpx

        from brainycat.config import settings

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": prompt}], "max_tokens": 200},
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                import json

                # Try to parse JSON from response
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1].strip("json\n ")
                result = json.loads(content)
                return {"classified": True, **result}
    except Exception as e:
        return {"error": str(e)}

    return {"classified": False}
