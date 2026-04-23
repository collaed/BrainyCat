"""Metadata enrichment from external sources."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client
from brainycat.sources import amazon, google_books, gutendex, loc, open_library


async def enrich_book(book_id: str) -> dict[str, Any]:
    """Fetch metadata from all sources and merge into the book record."""
    row = await fetch_one("SELECT * FROM books WHERE id = $1", UUID(book_id))
    if not row:
        return {"error": "not found"}

    title = row["title"]
    isbn = row["isbn"]

    # Query ALL sources in parallel (Calibre-style)
    import asyncio

    source_fns = [
        ("google_books", google_books.search),
        ("open_library", open_library.search),
        ("loc", loc.search),
        ("amazon", amazon.search),
        ("gutendex", gutendex.search),
    ]

    async def _fetch(name: str, fn: Any) -> tuple[str, dict[str, Any] | None]:
        try:
            r = await fn(title=title, isbn=isbn)
            return name, r
        except Exception:
            return name, None

    raw_results = await asyncio.gather(*[_fetch(n, fn) for n, fn in source_fns])

    results = []
    for source_name, r in raw_results:
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

    if not results:
        return {"enriched": False, "reason": "no results"}

    # Calibre-style merge: shortest title (least cruft), longest description,
    # shortest publisher, average rating, longest series name
    merged: dict[str, Any] = {}

    def _pick(field: str, shortest: bool = True) -> Any:
        vals = [r.get(field) for r in results if r.get(field)]
        if not vals:
            return None
        if isinstance(vals[0], str):
            vals.sort(key=len, reverse=not shortest)
        return vals[0]

    merged["title"] = _pick("title", shortest=True)  # shortest = least cruft
    merged["description"] = _pick("description", shortest=False)  # longest = most info
    merged["isbn"] = _pick("isbn", shortest=True)
    merged["cover_url"] = _pick("cover_url", shortest=False)
    merged["language"] = _pick("language", shortest=True)
    merged["publisher"] = _pick("publisher", shortest=True)  # shortest = least cruft
    merged["pubdate"] = _pick("pubdate", shortest=True)

    # Genres: union from all sources, deduplicated
    all_genres: list[str] = []
    for r in results:
        all_genres.extend(r.get("genres") or [])
    merged["genres"] = list(dict.fromkeys(all_genres))[:20]  # dedup, max 20

    # Authors: longest list (may include editors/translators)
    merged["authors"] = _pick("authors", shortest=False)

    # Rating: average across sources
    ratings = [r.get("rating") for r in results if r.get("rating") and r.get("rating") > 0]
    if ratings:
        merged["rating"] = round(sum(ratings) / len(ratings), 1)

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

    # Apply genres as tags
    if merged.get("genres"):
        for genre in merged["genres"][:10]:
            genre = genre.strip()
            if len(genre) < 2 or len(genre) > 50:
                continue
            await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", genre)
            tag_row = await fetch_one("SELECT id FROM tags WHERE name = $1", genre)
            if tag_row:
                await execute(
                    "INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    UUID(book_id),
                    tag_row["id"],
                )

    # Cover chain: source results → Apple Books → Bookcover API → OL → Generate
    if not row["cover_path"]:
        import os

        from brainycat.sources.covers import apple_cover, bookcover_api, is_dummy_cover
        from brainycat.storage import book_dir

        cover_url = merged.get("cover_url")
        # If no cover from enrichment sources, try dedicated cover APIs
        if not cover_url and isbn:
            cover_url = await apple_cover(isbn) or await bookcover_api(isbn)

        if cover_url:
            try:
                client = get_client()
                resp = await client.get(cover_url, timeout=15, follow_redirects=True)
                if resp.status_code == 200 and not is_dummy_cover(resp.content):
                    cover_path = os.path.join(book_dir(book_id), "cover.jpg")
                    with open(cover_path, "wb") as f:
                        f.write(resp.content)
                    await execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, UUID(book_id))
            except Exception:
                pass

    # Auto-apply series info from sources
    for r in results:
        series_name = r.get("series")
        series_idx = r.get("series_index")
        if series_name:
            # Check if book already in a series
            existing = await fetch_one("SELECT 1 FROM books_series WHERE book_id = $1", UUID(book_id))
            if not existing:
                await execute("INSERT INTO series (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", series_name)
                sid = await fetch_one("SELECT id FROM series WHERE name = $1", series_name)
                if sid:
                    await execute(
                        "INSERT INTO books_series (book_id, series_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        UUID(book_id),
                        sid["id"],
                    )
                    if series_idx:
                        await execute("UPDATE books SET series_index = $1 WHERE id = $2", float(series_idx), UUID(book_id))
                    await execute(
                        "INSERT INTO enrichment_log (book_id, method, success, details) VALUES ($1, 'series_detect', true, $2::jsonb)",
                        UUID(book_id),
                        json.dumps({"series": series_name, "index": series_idx, "source": r.get("source")}),
                    )
            break  # Use first series found

    # Update quality score
    score = _compute_quality(book_id, row, merged)
    await execute("UPDATE books SET quality_score = $1 WHERE id = $2", score, UUID(book_id))

    # Post-enrichment: writeback metadata into EPUB
    try:
        from brainycat.writeback import writeback_metadata

        await writeback_metadata(book_id)
    except Exception:
        pass

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
        from brainycat.config import settings

        client = get_client()
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
