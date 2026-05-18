"""Auto-detect series from title patterns like 'Book 1', 'Vol. 2', 'Tome 3'."""

from __future__ import annotations

import re
from typing import Any

from brainycat.db import execute, fetch_all, fetch_one

SERIES_PATTERNS = [
    # "Title (Series Name #3)"
    re.compile(r"\(([^)]+?)\s*#(\d+)\)"),
    # "Title [Series Name Book 3]"
    re.compile(r"\[([^]]+?)\s*(?:Book|Vol\.?|Volume|Tome|Part|#)\s*(\d+)\]"),
    # "Series Name, Book 3: Title" or "Series Name #3: Title"
    re.compile(r"^(.+?),?\s*(?:Book|Vol\.?|Volume|Tome|Part|#)\s*(\d+)\s*[: \-]"),
    # "Title - Book 3" or "Title - Vol 2"
    re.compile(r"^(.+?)\s*-\s*(?:Book|Vol\.?|Volume|Tome|Part)\s*(\d+)"),
    # "Title Book 3" at end
    re.compile(r"^(.+?)\s+(?:Book|Vol\.?|Volume|Tome)\s+(\d+)$"),
]


async def detect_series(limit: int = 100) -> dict[str, Any]:
    """Scan books without series and try to detect series from titles."""
    rows = await fetch_all(
        """
        SELECT b.id, b.title FROM books b
        WHERE NOT EXISTS (SELECT 1 FROM books_series bs WHERE bs.book_id = b.id)
        LIMIT $1
    """,
        limit,
    )

    detected = 0
    for r in rows:
        title = r["title"] or ""
        for pattern in SERIES_PATTERNS:
            m = pattern.search(title)
            if m:
                series_name = m.group(1).strip()
                series_idx = int(m.group(2))

                if len(series_name) < 2 or len(series_name) > 100:
                    continue

                # Find or create series
                series = await fetch_one("SELECT id FROM series WHERE name = $1", series_name)
                if not series:
                    series = await fetch_one(
                        "INSERT INTO series (name, sort_name) VALUES ($1, $1) RETURNING id",
                        series_name,
                    )
                if series:
                    await execute(
                        "INSERT INTO books_series (book_id, series_id, series_index) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        r["id"],
                        series["id"],
                        series_idx,
                    )
                    detected += 1
                break

    return {"detected": detected, "checked": len(rows)}


async def get_series_with_gaps(limit: int = 20) -> list[dict[str, Any]]:
    """Find series in the library and identify missing volumes."""
    rows = await fetch_all(
        """
        SELECT s.id, s.name, 
               array_agg(b.id ORDER BY COALESCE(b.series_index, 0)) as book_ids,
               array_agg(b.title ORDER BY COALESCE(b.series_index, 0)) as titles,
               array_agg(COALESCE(b.series_index, 0) ORDER BY COALESCE(b.series_index, 0)) as indices,
               count(*) as count
        FROM series s
        JOIN books_series bs ON bs.series_id = s.id
        JOIN books b ON b.id = bs.book_id
        GROUP BY s.id
        HAVING count(*) >= 2
        ORDER BY count(*) DESC
        LIMIT $1
        """,
        limit,
    )
    results = []
    for r in rows:
        indices = [int(i) for i in r["indices"] if i > 0]
        if not indices:
            continue
        max_idx = max(indices)
        owned = set(indices)
        missing = [i for i in range(1, max_idx + 1) if i not in owned]
        results.append({
            "series_id": str(r["id"]),
            "name": r["name"],
            "count": r["count"],
            "books": [{"id": str(bid), "title": t, "index": idx}
                      for bid, t, idx in zip(r["book_ids"], r["titles"], r["indices"])],
            "missing_indices": missing,
            "complete": len(missing) == 0,
        })
    return results


async def search_missing_in_series(series_id: str) -> list[dict[str, Any]]:
    """Search online catalogs for missing books in a series."""
    from brainycat.http_client import get_client
    from brainycat.rate_limit import rate_limiter

    series = await fetch_one("SELECT name FROM series WHERE id = $1", __import__("uuid").UUID(series_id))
    if not series:
        return []

    # Get what we already have
    owned = await fetch_all(
        "SELECT b.series_index FROM books b JOIN books_series bs ON bs.book_id = b.id WHERE bs.series_id = $1",
        __import__("uuid").UUID(series_id),
    )
    owned_indices = {int(r["series_index"]) for r in owned if r["series_index"]}

    # Search Google Books for the series
    await rate_limiter.wait("google")
    client = get_client()
    try:
        resp = await client.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": f'"{series["name"]}"', "maxResults": 20},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        items = resp.json().get("items", [])
        missing = []
        for item in items:
            vi = item["volumeInfo"]
            title = vi.get("title", "")
            # Try to extract series index from title
            for pattern in SERIES_PATTERNS:
                m = pattern.search(title)
                if m:
                    idx = int(m.group(2))
                    if idx not in owned_indices:
                        missing.append({
                            "title": title,
                            "authors": vi.get("authors", []),
                            "index": idx,
                            "isbn": next((i["identifier"] for i in vi.get("industryIdentifiers", []) if "ISBN" in i["type"]), None),
                        })
                    break
        return missing
    except Exception:
        return []
