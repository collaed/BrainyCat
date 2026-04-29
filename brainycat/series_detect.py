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
