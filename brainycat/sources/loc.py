"""Library of Congress API — highest quality official metadata."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://www.loc.gov/books"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Library of Congress."""
    params: dict[str, Any] = {"fo": "json", "c": 5}
    if isbn:
        params["q"] = isbn
    elif title:
        params["q"] = title
    else:
        return None

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(API_URL, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:
        return None

    results = data.get("results", [])
    if not results:
        return None

    item = results[0]
    contributors = item.get("contributor", [])
    subjects = item.get("subject", [])
    languages = item.get("language", [])

    return {
        "source": "loc",
        "title": item.get("title"),
        "description": item.get("description", [None])[0] if item.get("description") else None,
        "isbn": isbn,
        "language": languages[0] if languages else None,
        "publisher": None,
        "pubdate": item.get("date"),
        "genres": subjects[:10],
        "cover_url": item.get("image_url", [None])[0] if item.get("image_url") else None,
        "authors": contributors,
        "loc_url": item.get("url"),
    }
