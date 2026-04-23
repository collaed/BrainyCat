"""Edelweiss — publisher catalog metadata source.

Edelweiss+ is a catalog maintained by book publishers. Good for:
- Recent/upcoming books (publishers list them before release)
- Accurate ISBNs, descriptions, covers
- Publisher and imprint data
"""

from __future__ import annotations

import re
from typing import Any

from brainycat.http_client import get_client

SEARCH_URL = "https://www.edelweiss.plus/GetTitlesBySearch"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Edelweiss publisher catalog."""
    query = isbn or title
    if not query:
        return None
    try:
        client = get_client()
        resp = await client.get(
            "https://www.edelweiss.plus/browse",
            params={"term": query},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return None

        # Parse results from HTML
        text = resp.text
        results = []
        for m in re.finditer(
            r'data-isbn="(\d{13})".*?data-title="([^"]*)".*?data-author="([^"]*)"',
            text,
            re.DOTALL,
        ):
            results.append(
                {
                    "source": "edelweiss",
                    "isbn": m.group(1),
                    "title": m.group(2),
                    "authors": [m.group(3)] if m.group(3) else [],
                }
            )
            if len(results) >= 5:
                break

        if results:
            return results[0]  # Return best match
    except Exception:
        pass
    return None
