"""LibriVox API — public domain audiobooks."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://librivox.org/api/feed/audiobooks"


async def search(title: str | None = None, author: str | None = None, limit: int = 20) -> dict[str, Any]:
    params: dict[str, Any] = {"format": "json", "limit": limit}
    # LibriVox can't combine title+author — search one at a time
    if title:
        params["title"] = title
    elif author:
        params["author"] = author
    else:
        return {"books": []}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(API_URL, params=params)
            if resp.status_code == 200:
                data = resp.json()
                books_raw = data.get("books", [])
                if isinstance(books_raw, list) and books_raw:
                    return {"books": [_parse(b) for b in books_raw]}
    except Exception:
        pass
    # Fallback: if title search failed and we have author, retry with author only
    if title and author:
        return await search(title=None, author=author, limit=limit)
    return {"books": []}


async def get_book(librivox_id: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(API_URL, params={"id": librivox_id, "format": "json"})
            if resp.status_code != 200:
                return None
            data = resp.json()
        books = data.get("books", [])
        return _parse(books[0]) if books else None
    except Exception:
        return None


async def get_chapters(rss_url: str) -> list[dict[str, Any]]:
    """Parse RSS feed to get individual chapter MP3 URLs."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(rss_url)
            if resp.status_code != 200:
                return []
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")
        chapters = []
        for item in soup.find_all("item"):
            enc = item.find("enclosure")
            if enc and enc.get("url"):
                chapters.append(
                    {
                        "title": item.find("title").text if item.find("title") else f"Chapter {len(chapters) + 1}",
                        "url": enc["url"],
                        "duration": item.find("itunes:duration").text if item.find("itunes:duration") else None,
                    }
                )
        return chapters
    except Exception:
        return []


def _parse(data: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for a in data.get("authors", []):
        name = f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
        if name:
            authors.append(name)
    return {
        "source": "librivox",
        "librivox_id": data.get("id"),
        "title": data.get("title"),
        "authors": authors,
        "language": data.get("language"),
        "description": data.get("description"),
        "url_rss": data.get("url_rss"),
        "url_zip": data.get("url_zip_file"),
        "url_librivox": data.get("url_librivox"),
        "totaltime": data.get("totaltime"),
        "num_sections": data.get("num_sections"),
    }
