"""Google Books API metadata source."""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client

API_URL = "https://www.googleapis.com/books/v1/volumes"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Google Books by ISBN or title."""
    q = f"isbn:{isbn}" if isbn else title
    if not q:
        return None
    client = get_client()
    from brainycat.config import settings

    params: dict[str, Any] = {"q": q, "maxResults": 1}
    if settings.google_books_api_key:
        params["key"] = settings.google_books_api_key
    resp = await client.get(API_URL, params=params)
    if resp.status_code == 429:
        from brainycat.rate_limit import rate_limiter
        rate_limiter.report_failure("google")
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    items = data.get("items", [])
    if not items:
        return None
    info = items[0].get("volumeInfo", {})
    cover = info.get("imageLinks", {}).get("thumbnail")
    # Extract series from subtitle (e.g. 'Book 1 of the Expanse')
    subtitle = info.get("subtitle", "")
    series_name = None
    series_index = None
    if subtitle:
        import re

        m = re.search(r"(?:Book|Vol\.?|Volume|#)\s*(\d+)\s+(?:of|in|:)\s+(?:the\s+)?(.+?)(?:\s*\(|$)", subtitle, re.IGNORECASE)
        if m:
            series_index = int(m.group(1))
            series_name = m.group(2).strip()
        else:
            m = re.search(r"(.+?)\s+(?:Series|Trilogy|Saga|Cycle),?\s*(?:Book|#|Vol)\s*(\d+)", subtitle, re.IGNORECASE)
            if m:
                series_name = m.group(1).strip()
                series_index = int(m.group(2))

    return {
        "source": "google_books",
        "title": info.get("title"),
        "series": series_name,
        "series_index": series_index,
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
