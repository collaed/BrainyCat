"""Catalog cache — local mirror of Gutenberg + LibriVox for instant search.

Gutenberg: ~70K books via gutendex paginated API
LibriVox: ~20K audiobooks via their API
Cross-links: pre-computed by author last name + title keyword matching

Refresh: run sync_gutenberg() and sync_librivox() periodically (weekly).
"""

from __future__ import annotations

from typing import Any

import httpx

from brainycat.db import execute, fetch_all, fetch_one

GUTENDEX_URL = "https://gutendex.com/books"
LIBRIVOX_URL = "https://librivox.org/api/feed/audiobooks"


async def sync_gutenberg(max_pages: int = 50, languages: list[str] | None = None) -> dict[str, int]:
    """Download Gutenberg catalog into local cache. ~70K books, paginated 32/page."""
    inserted = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        lang_param = ",".join(languages) if languages else ""
        url: str | None = GUTENDEX_URL + "?page=1" + (f"&languages={lang_param}" if lang_param else "")
        page = 0
        while url and page < max_pages:
            page += 1
            resp = await client.get(url)
            if resp.status_code != 200:
                break
            data = resp.json()
            for b in data.get("results", []):
                gid = f"gut_{b['id']}"
                authors = [a["name"] for a in b.get("authors", [])]
                formats = b.get("formats", {})
                await execute(
                    """
                    INSERT INTO catalog_cache (id, source, title, authors, language, genres, cover_url, epub_url, download_count)
                    VALUES ($1, 'gutenberg', $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (id) DO UPDATE SET title=$2, authors=$3, download_count=$8, cached_at=now()
                """,
                    gid,
                    b.get("title"),
                    authors,
                    next(iter(b.get("languages", [])), "en"),
                    b.get("subjects", []),
                    formats.get("image/jpeg"),
                    formats.get("application/epub+zip"),
                    b.get("download_count", 0),
                )
                inserted += 1
            url = data.get("next")
    return {"inserted": inserted, "pages": page}


async def sync_librivox(max_pages: int = 50, languages: list[str] | None = None) -> dict[str, int]:
    """Download LibriVox catalog into local cache. ~20K audiobooks."""
    inserted = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        offset = 0
        limit = 50
        for _page in range(max_pages):
            resp = await client.get(LIBRIVOX_URL, params={"format": "json", "limit": limit, "offset": offset})
            if resp.status_code != 200:
                break
            data = resp.json()
            books = data.get("books", [])
            if not isinstance(books, list) or not books:
                break
            for b in books:
                lid = f"lv_{b['id']}"
                authors = [f"{a.get('first_name', '')} {a.get('last_name', '')}".strip() for a in b.get("authors", [])]
                await execute(
                    """
                    INSERT INTO catalog_cache (id, source, title, authors, language, rss_url, totaltime, num_sections)
                    VALUES ($1, 'librivox', $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (id) DO UPDATE SET title=$2, authors=$3, cached_at=now()
                """,
                    lid,
                    b.get("title"),
                    authors,
                    b.get("language", ""),
                    b.get("url_rss"),
                    b.get("totaltime"),
                    int(b.get("num_sections") or 0),
                )
                inserted += 1
            offset += limit
    return {"inserted": inserted, "pages": max_pages}


async def compute_crosslinks() -> dict[str, int]:
    """Pre-compute Gutenberg↔LibriVox links by author last name + title words."""
    # Get all LibriVox entries indexed by author last name
    lv_rows = await fetch_all("SELECT id, title, authors FROM catalog_cache WHERE source='librivox'")
    lv_by_author: dict[str, list[dict]] = {}
    for r in lv_rows:
        for a in r["authors"] or []:
            last = a.strip().split()[-1].lower() if a.strip() else ""
            if last:
                lv_by_author.setdefault(last, []).append({"id": r["id"], "title": r["title"]})

    # Match Gutenberg books
    gut_rows = await fetch_all("SELECT id, title, authors FROM catalog_cache WHERE source='gutenberg' AND crosslink_id IS NULL")
    linked = 0
    for g in gut_rows:
        for a in g["authors"] or []:
            last = a.strip().split(",")[0].split()[-1].lower() if a.strip() else ""
            candidates = lv_by_author.get(last, [])
            g_words = {w.lower() for w in (g["title"] or "").split() if len(w) > 3}
            for c in candidates:
                c_words = {w.lower() for w in (c["title"] or "").split() if len(w) > 3}
                if g_words & c_words:
                    await execute("UPDATE catalog_cache SET crosslink_id=$1 WHERE id=$2", c["id"], g["id"])
                    await execute("UPDATE catalog_cache SET crosslink_id=$1 WHERE id=$2", g["id"], c["id"])
                    linked += 1
                    break
    return {"linked": linked}


async def search_cached(query: str, source: str = "gutenberg", language: str = "en", limit: int = 30) -> dict[str, Any]:
    """Search the local catalog cache — instant, no API calls."""
    rows = await fetch_all(
        """
        SELECT c.*, cl.title as crosslink_title, cl.totaltime as crosslink_time,
               cl.num_sections as crosslink_sections, cl.id as crosslink_raw_id
        FROM catalog_cache c
        LEFT JOIN catalog_cache cl ON cl.id = c.crosslink_id
        WHERE c.source = $1
          AND ($2 = '' OR c.language = $2)
          AND ($3 = '' OR c.title ILIKE '%' || $3 || '%' OR EXISTS (SELECT 1 FROM unnest(c.authors) a WHERE a ILIKE '%' || $3 || '%'))
        ORDER BY c.download_count DESC NULLS LAST
        LIMIT $4
    """,
        source,
        language or "",
        query or "",
        limit,
    )

    books = []
    for r in rows:
        book: dict[str, Any] = {
            "source": r["source"],
            "title": r["title"],
            "authors": r["authors"] or [],
            "language": r["language"],
            "cover_url": r["cover_url"],
            "download_count": r["download_count"],
        }
        if r["source"] == "gutenberg":
            book["gutenberg_id"] = int(r["id"].replace("gut_", ""))
            book["epub_url"] = r["epub_url"]
        else:
            book["librivox_id"] = r["id"].replace("lv_", "")
            book["totaltime"] = r["totaltime"]
            book["num_sections"] = r["num_sections"]

        if r["crosslink_title"]:
            xlink = {"title": r["crosslink_title"]}
            if r["source"] == "gutenberg":
                xlink["librivox_id"] = r["crosslink_raw_id"].replace("lv_", "")
                xlink["totaltime"] = r["crosslink_time"]
                xlink["num_sections"] = r["crosslink_sections"]
            else:
                xlink["gutenberg_id"] = int(r["crosslink_raw_id"].replace("gut_", ""))
            book["audiobook" if r["source"] == "gutenberg" else "ebook"] = xlink

        books.append(book)

    total = await fetch_one("SELECT count(*) as n FROM catalog_cache WHERE source=$1 AND ($2='' OR language=$2)", source, language or "")
    return {"count": total["n"] if total else 0, "books": books}
