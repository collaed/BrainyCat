"""LibriVox API — public domain audiobooks."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://librivox.org/api/feed/audiobooks"


async def search(title: str | None = None, author: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Search LibriVox catalog."""
    params: dict[str, Any] = {"format": "json", "limit": limit}
    if title:
        params["title"] = f"^{title}"
    if author:
        params["author"] = f"^{author}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(API_URL, params=params)
        if resp.status_code != 200:
            return {"books": []}
        data = resp.json()
    books_raw = data.get("books", [])
    if isinstance(books_raw, dict) and books_raw.get("error"):
        return {"books": []}
    return {"books": [_parse(b) for b in books_raw]}


async def get_book(librivox_id: str) -> dict[str, Any] | None:
    """Get a single LibriVox audiobook."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(API_URL, params={"id": librivox_id, "format": "json"})
        if resp.status_code != 200:
            return None
        data = resp.json()
    books = data.get("books", [])
    return _parse(books[0]) if books else None


def _parse(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "librivox",
        "librivox_id": data.get("id"),
        "title": data.get("title"),
        "authors": [{"name": a.get("first_name", "") + " " + a.get("last_name", "")} for a in data.get("authors", [])],
        "language": data.get("language"),
        "description": data.get("description"),
        "url_rss": data.get("url_rss"),
        "url_zip": data.get("url_zip_file"),
        "url_librivox": data.get("url_librivox"),
        "totaltime": data.get("totaltime"),
        "num_sections": data.get("num_sections"),
    }
