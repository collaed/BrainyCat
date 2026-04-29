"""Metadata enrichment from external sources."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client
from brainycat.sources import google_books, gutendex, open_library


def _search_variants(title: str) -> list[str]:
    """Generate search-friendly variants from a dirty title."""
    import re

    variants = []
    t = title

    # Strip common prefixes (PP., OReilly., Apress.)
    t = re.sub(r"^(?:PP|OReilly|Apress|Packt|Manning|Wiley)\.\s*", "", t)
    # Dots to spaces
    t = t.replace(".", " ").replace("_", " ")
    # Remove year/month patterns (Jan.2014, Dec.2013, (2021), (2022))
    t = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4}", "", t)
    t = re.sub(r"\(\d{4}\)", "", t)
    # Remove edition markers
    t = re.sub(r"\b\d+(?:st|nd|rd|th)\s+(?:Edition|Ed\.?)\b", "", t, flags=re.IGNORECASE)
    # Remove publisher artifacts
    t = re.sub(r"\b(?:libgen\.li|Anna.s Archive|z-lib)\b", "", t, flags=re.IGNORECASE)
    # Remove [tags] and (tags)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"\([^)]*\)", "", t)
    # Remove author prefix pattern: "Author - Title"
    if " - " in t:
        parts = t.split(" - ", 1)
        if len(parts[0].split()) <= 4:  # likely author
            variants.append(parts[1].strip())
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()

    if t and t != title:
        variants.insert(0, t)
    # Also try just the first few meaningful words
    words = [w for w in t.split() if len(w) > 2]
    if len(words) > 3:
        variants.append(" ".join(words[:4]))

    return variants or [title]


async def enrich_book(book_id: str) -> dict[str, Any]:
    """Fetch metadata from all sources and merge into the book record."""
    row = await fetch_one("SELECT * FROM books WHERE id = $1", UUID(book_id))
    if not row:
        return {"error": "not found"}

    title = row["title"]
    isbn = row["isbn"]

    # Query ALL sources in parallel (Calibre-style)
    import asyncio

    results: list[dict[str, Any]] = []

    # Clean title for better query matching
    from brainycat.title_confidence import build_enrichment_query, clean_title_for_query
    from brainycat.relevance_guard import is_relevant

    query_title = build_enrichment_query(title)

    # Primary: Intello unified lookup (re-enabled after fix)
    try:
        import asyncio as _aio

        from brainycat.config import settings

        async with _aio.timeout(15):
            client = get_client()
            lookup_body: dict[str, Any] = {"query": query_title, "media_type": "book"}
            if isbn:
                lookup_body["isbn"] = isbn
            resp = await client.post(
                f"{settings.intello_url}/api/v1/lookup",
                json=lookup_body,
                timeout=15,
            )
        if resp.status_code == 200:
            lookup_data = resp.json()
            for source_name, source_data in lookup_data.get("sources", {}).items():
                for result in source_data.get("results", [])[:1]:
                    # Relevance guard: reject results that don't match our book
                    result_title = result.get("title", "")
                    result_isbn = result.get("isbn", "")
                    if is_relevant(title, result_title, result_isbn, isbn):
                        results.append(result)
                    else:
                        await log.ainfo("relevance_rejected", book_title=title, result_title=result_title)
                    await execute(
                        "INSERT INTO enrichment_log (book_id, method, success, details) VALUES ($1, $2, true, $3::jsonb)",
                        UUID(book_id),
                        source_name,
                        "{}",
                    )
    except Exception:
        pass

    # Fallback: direct source queries (if Intello lookup returned nothing)
    if not results:
        source_fns = [
            ("open_library", open_library.search),
            ("google_books", google_books.search),
            ("gutendex", gutendex.search),
        ]

    async def _fetch(name: str, fn: Any) -> tuple[str, dict[str, Any] | None]:
        from brainycat.retry import with_retry

        try:
            async with asyncio.timeout(15):  # 15s max per source
                r = await with_retry(fn, title=title, isbn=isbn, retries=1, delay=2.0)
                if not r and not isbn:
                    for variant in _search_variants(title)[1:]:
                        r = await with_retry(fn, title=variant, isbn=isbn, retries=0, delay=0)
                        if r:
                            break
            return name, r
        except TimeoutError:
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

    # Map tags to BISAC/Thema codes
    if merged.get("genres"):
        import json as _json

        from brainycat.bisac import map_tag_to_bisac

        codes = []
        for g in merged["genres"]:
            m = map_tag_to_bisac(g)
            if m:
                codes.append({"bisac": m[0], "name": m[1], "thema": m[2], "confidence": "confirmed"})
        if not codes:
            # LLM fallback for unmapped genres
            from brainycat.bisac import llm_classify_bisac

            codes = await llm_classify_bisac(
                merged.get("title", ""),
                merged.get("author", ""),
                merged["genres"],
                merged.get("description", ""),
            )
        if codes:
            await execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
                _json.dumps({"bisac_codes": codes}),
                UUID(book_id),
            )

    # Store pubdate from enrichment
    if merged.get("pubdate") and not row.get("pubdate"):
        try:
            from dateutil.parser import parse as _parse_date

            pd = _parse_date(str(merged["pubdate"]))
            await execute("UPDATE books SET pubdate = $1 WHERE id = $2", pd, UUID(book_id))
        except Exception:
            pass

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
                    from brainycat.atomic import atomic_write

                    with atomic_write(cover_path) as f:
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

    # Store Open Library Work ID + edition IDs for "you already own this" detection
    for r in results:
        work_key = r.get("ol_work_key")
        if work_key:
            import json as _json

            await execute(
                "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{ol_work_id}', $1::jsonb) WHERE id = $2",
                _json.dumps(work_key),
                UUID(book_id),
            )
            break  # One work ID is enough

    # Post-enrichment: writeback metadata into EPUB
    try:
        from brainycat.writeback import writeback_metadata

        await writeback_metadata(book_id)
    except Exception:
        pass

    # Auto-writeback metadata to EPUB file
    try:
        from brainycat.writeback import writeback_metadata

        await writeback_metadata(book_id)
    except Exception:
        pass

    # Check if we can contribute back to open databases
    try:
        from brainycat.contribute import contribute_back

        await contribute_back(book_id)
    except Exception:
        pass

    return {"enriched": True, "quality_score": score, "sources": len(results)}


def _compute_quality(book_id: str, row: Any, merged: dict[str, Any]) -> int:
    """Weighted completeness score 0-100 (Calibre-aligned)."""
    rd = dict(row)  # asyncpg Record → dict for safe .get()
    score = 0

    def _val(field: str) -> Any:
        return merged.get(field) or rd.get(field)

    # Title (10)
    title = _val("title")
    if title and str(title).lower() not in ("unknown", "untitled"):
        score += 10
    # Author (15)
    score += 15
    # Cover (15)
    if _val("cover_path"):
        score += 15
    # Description (15)
    desc = _val("description")
    if desc and len(str(desc)) > 20:
        score += 15
    # ISBN (10)
    if _val("isbn"):
        score += 10
    # Language (5)
    if _val("language"):
        score += 5
    # Publisher (5)
    extra = rd.get("extra_metadata") or {}
    if isinstance(extra, str):
        import json as _json

        try:
            extra = _json.loads(extra)
        except Exception:
            extra = {}
    if merged.get("publisher") or extra.get("publisher"):
        score += 5
    # Pubdate (5)
    if _val("pubdate"):
        score += 5
    # Tags/genres (10)
    if merged.get("genres"):
        score += 10
    # Series (10)
    if merged.get("series"):
        score += 10
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
            json={"model": "auto", "messages": [{"role": "user", "content": prompt}], "task_hint": "classification", "max_tokens": 200},
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
