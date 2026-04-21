"""Gutendex API — Project Gutenberg catalog."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://gutendex.com/books"


async def search(
    title: str | None = None,
    isbn: str | None = None,
    language: str | None = None,
    topic: str | None = None,
    page: int = 1,
) -> dict[str, Any] | None:
    """Search Gutendex catalog."""
    params: dict[str, Any] = {"page": page}
    if title:
        params["search"] = title
    if language:
        params["languages"] = language
    if topic:
        params["topic"] = topic
    if not params.get("search") and not topic:
        return None

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(API_URL, params=params)
        if resp.status_code != 200:
            return None
        data = resp.json()

    results = data.get("results", [])
    if not results:
        return None

    # Return first result for enrichment, full list for catalog browsing
    first = results[0]
    return _parse_book(first)


async def browse(language: str = "en", topic: str | None = None, page: int = 1) -> dict[str, Any]:
    """Browse Gutenberg catalog."""
    params: dict[str, Any] = {"languages": language, "page": page, "sort": "popular"}
    if topic:
        params["topic"] = topic
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(API_URL, params=params)
        data = resp.json() if resp.status_code == 200 else {}
    return {
        "count": data.get("count", 0),
        "books": [_parse_book(b) for b in data.get("results", [])],
        "next": data.get("next"),
        "previous": data.get("previous"),
    }


async def get_book(gutenberg_id: int) -> dict[str, Any] | None:
    """Get a single Gutenberg book by ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_URL}/{gutenberg_id}")
        if resp.status_code != 200:
            return None
        return _parse_book(resp.json())


def _parse_book(data: dict[str, Any]) -> dict[str, Any]:
    authors = [a["name"] for a in data.get("authors", [])]
    formats = data.get("formats", {})
    epub_url = formats.get("application/epub+zip")
    txt_url = next((v for k, v in formats.items() if "text/plain" in k), None)
    cover_url = formats.get("image/jpeg")
    return {
        "source": "gutenberg",
        "gutenberg_id": data.get("id"),
        "title": data.get("title"),
        "authors": authors,
        "description": None,
        "isbn": None,
        "language": next(iter(data.get("languages", [])), None),
        "genres": data.get("subjects", []),
        "cover_url": cover_url,
        "epub_url": epub_url,
        "txt_url": txt_url,
        "download_count": data.get("download_count"),
    }
