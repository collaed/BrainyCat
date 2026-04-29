"""Readarr integration — search and auto-download wanted books.

Connects to a Readarr instance to search for books on your want-to-read list.

Config: BRAINYCAT_READARR_URL + BRAINYCAT_READARR_API_KEY
"""

from __future__ import annotations

from typing import Any


async def search_readarr(query: str) -> dict[str, Any]:
    """Search Readarr for a book."""
    import httpx

    from brainycat.config import settings

    url = getattr(settings, "readarr_url", "") or ""
    key = getattr(settings, "readarr_api_key", "") or ""
    if not url or not key:
        return {"error": "Readarr not configured (set BRAINYCAT_READARR_URL + BRAINYCAT_READARR_API_KEY)"}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{url.rstrip('/')}/api/v1/search",
            params={"term": query},
            headers={"X-Api-Key": key},
        )
        if r.status_code == 200:
            return {"results": r.json()[:10]}
        return {"error": f"Readarr returned {r.status_code}"}


async def add_to_readarr(title: str, author: str) -> dict[str, Any]:
    """Add a book to Readarr's wanted list."""
    import httpx

    from brainycat.config import settings

    url = getattr(settings, "readarr_url", "") or ""
    key = getattr(settings, "readarr_api_key", "") or ""
    if not url or not key:
        return {"error": "Readarr not configured"}

    # Search first
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{url.rstrip('/')}/api/v1/search",
            params={"term": f"{title} {author}"},
            headers={"X-Api-Key": key},
        )
        if r.status_code != 200:
            return {"error": f"Search failed: {r.status_code}"}
        results = r.json()
        if not results:
            return {"error": "Not found in Readarr"}

        # Add first result
        book = results[0]
        r2 = await client.post(
            f"{url.rstrip('/')}/api/v1/book",
            json=book,
            headers={"X-Api-Key": key},
        )
        return {"added": r2.status_code == 201, "title": book.get("title")}
