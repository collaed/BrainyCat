"""ISBNdb metadata — requires API key from isbndb.com ($49/mo) or ibdb.dev access.

Note: ibdb.dev is a web UI without public API. CWA has a special arrangement.
For now this source is disabled unless BRAINYCAT_ISBNDB_KEY is set.
"""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    import os

    api_key = os.getenv("BRAINYCAT_ISBNDB_KEY", "")
    if not api_key:
        return None  # Disabled without API key
    """Search ISBNdb via ibdb.dev proxy."""
    if not isbn and not title:
        return None

    client = get_client()
    headers = {"Authorization": api_key}
    try:
        if isbn:
            resp = await client.get(f"https://api2.isbndb.com/book/{isbn}", headers=headers, timeout=8)
        else:
            resp = await client.get(f"https://api2.isbndb.com/books/{title}", headers=headers, timeout=8)

        if resp.status_code != 200:
            return None

        data = resp.json()

        # ibdb.dev returns different shapes for ISBN vs search
        if isbn:
            book = data
        else:
            results = data.get("books", data.get("results", []))
            if not results:
                return None
            book = results[0]

        return {
            "title": book.get("title", ""),
            "authors": book.get("authors", []),
            "publisher": book.get("publisher", ""),
            "pubdate": book.get("date_published") or book.get("publish_date", ""),
            "description": book.get("synopsis") or book.get("overview", ""),
            "isbn": book.get("isbn13") or book.get("isbn", ""),
            "pages": book.get("pages"),
            "cover_url": book.get("image", ""),
            "source": "isbndb",
        }
    except Exception:
        return None
