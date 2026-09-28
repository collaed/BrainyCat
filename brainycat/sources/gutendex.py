"""Gutendex API — Project Gutenberg catalog."""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client

API_URL = "https://gutendex.com/books"


async def search(
    title: str | None = None, isbn: str | None = None, language: str | None = None, topic: str | None = None, page: int = 1
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"page": page}
    if title:
        params["search"] = title
    if language:
        params["languages"] = language
    if topic:
        params["topic"] = topic
    if not params.get("search") and not topic:
        return None

    try:
        client = get_client()
        resp = await client.get(API_URL, params=params, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        # gutendex.com is occasionally unreachable/slow from some networks; fail fast rather than
        # eating the caller's whole per-source time budget (was the root cause of enrichment timeouts).
        return None

    results = data.get("results", [])
    if not results:
        return None
    return {"count": data.get("count", 0), "books": [_parse_book(b) for b in results]}


async def browse(language: str = "en", topic: str | None = None, page: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {"languages": language, "page": page, "sort": "popular"}
    if topic:
        params["topic"] = topic
    client = get_client()
    try:
        resp = await client.get(API_URL, params=params, timeout=8)
        data = resp.json() if resp.status_code == 200 else {}
    except Exception:
        data = {}
    return {"count": data.get("count", 0), "books": [_parse_book(b) for b in data.get("results", [])]}


async def get_book(gutenberg_id: int) -> dict[str, Any] | None:
    client = get_client()
    try:
        resp = await client.get(f"{API_URL}/{gutenberg_id}", timeout=8)
        if resp.status_code != 200:
            return None
        return _parse_book(resp.json())
    except Exception:
        return None


def _parse_book(data: dict[str, Any]) -> dict[str, Any]:
    authors = [a["name"] for a in data.get("authors", [])]
    formats = data.get("formats", {})
    epub_url = formats.get("application/epub+zip")
    cover_url = formats.get("image/jpeg")
    return {
        "source": "gutenberg",
        "gutenberg_id": data.get("id"),
        "title": data.get("title"),
        "authors": authors,
        "language": next(iter(data.get("languages", [])), None),
        "genres": data.get("subjects", []),
        "cover_url": cover_url,
        "epub_url": epub_url,
        "download_count": data.get("download_count"),
    }
