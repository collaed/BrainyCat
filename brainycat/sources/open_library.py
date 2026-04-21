"""Open Library API metadata source."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://openlibrary.org"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Open Library by ISBN or title."""
    async with httpx.AsyncClient(timeout=10) as client:
        if isbn:
            resp = await client.get(f"{API_URL}/isbn/{isbn}.json")
            if resp.status_code == 200:
                return _parse_edition(resp.json())
        if title:
            resp = await client.get(f"{API_URL}/search.json", params={"title": title, "limit": 1})
            if resp.status_code == 200:
                docs = resp.json().get("docs", [])
                if docs:
                    return _parse_search(docs[0])
    return None


def _parse_edition(data: dict[str, Any]) -> dict[str, Any]:
    covers = data.get("covers", [])
    return {
        "source": "open_library",
        "title": data.get("title"),
        "description": data.get("description", {}).get("value") if isinstance(data.get("description"), dict) else data.get("description"),
        "isbn": next(iter(data.get("isbn_13", data.get("isbn_10", []))), None),
        "language": None,
        "publisher": next(iter(data.get("publishers", [])), None),
        "pubdate": data.get("publish_date"),
        "genres": data.get("subjects", [])[:10],
        "cover_url": f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg" if covers else None,
    }


def _parse_search(doc: dict[str, Any]) -> dict[str, Any]:
    cover_id = doc.get("cover_i")
    return {
        "source": "open_library",
        "title": doc.get("title"),
        "description": None,
        "isbn": next(iter(doc.get("isbn", [])), None),
        "language": next(iter(doc.get("language", [])), None),
        "publisher": next(iter(doc.get("publisher", [])), None),
        "pubdate": str(doc.get("first_publish_year", "")),
        "genres": doc.get("subject", [])[:10],
        "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
        "rating": doc.get("ratings_average"),
    }
