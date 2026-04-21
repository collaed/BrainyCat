"""Google Books API metadata source."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://www.googleapis.com/books/v1/volumes"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Google Books by ISBN or title."""
    q = f"isbn:{isbn}" if isbn else title
    if not q:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(API_URL, params={"q": q, "maxResults": 1})
        if resp.status_code != 200:
            return None
        data = resp.json()
    items = data.get("items", [])
    if not items:
        return None
    info = items[0].get("volumeInfo", {})
    cover = info.get("imageLinks", {}).get("thumbnail")
    return {
        "source": "google_books",
        "title": info.get("title"),
        "description": info.get("description"),
        "isbn": next((i["identifier"] for i in info.get("industryIdentifiers", []) if i["type"] == "ISBN_13"), None),
        "language": info.get("language"),
        "publisher": info.get("publisher"),
        "pubdate": info.get("publishedDate"),
        "genres": info.get("categories", []),
        "cover_url": cover.replace("http://", "https://") if cover else None,
        "rating": info.get("averageRating"),
        "rating_count": info.get("ratingsCount"),
    }
