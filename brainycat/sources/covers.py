"""Cover sources — Apple Books, Bookcover API, and cover validation.

Cover fallback chain:
Embedded → Google Books → Apple Books → Open Library → Bookcover API → Amazon → Generate
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

# Known dummy/placeholder cover MD5s (Google Books returns these instead of 404)
DUMMY_COVER_MD5S = {
    "0de4383ebad0adad5eeb8975cd796657",
    "a64fa89d7ebc97075c1d363fc5fea71f",
}


async def apple_cover(isbn: str) -> str | None:
    """Get high-res cover from Apple Books. Free, no auth."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://itunes.apple.com/lookup?isbn={isbn}&entity=ebook")
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    art = results[0].get("artworkUrl100", "")
                    return art.replace("100x100", "600x600") if art else None
    except Exception:
        pass
    return None


async def bookcover_api(isbn: str) -> str | None:
    """Aggregated cover search from bookcover.longitood.com. Free, no auth."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://bookcover.longitood.com/bookcover/{isbn}")
            if r.status_code == 200:
                return r.json().get("url")
    except Exception:
        pass
    return None


async def open_library_cover(isbn: str) -> str | None:
    """Get cover from Open Library by ISBN."""
    url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.head(url, follow_redirects=True)
            if r.status_code == 200:
                return url
    except Exception:
        pass
    return None


def is_dummy_cover(data: bytes) -> bool:
    """Check if cover data is a known placeholder/dummy image."""
    if len(data) < 1000:
        return True  # Too small to be a real cover
    md5 = hashlib.md5(data).hexdigest()
    return md5 in DUMMY_COVER_MD5S


async def google_images_cover(title: str, author: str = "") -> str | None:
    """Search Google Images for book covers (like Calibre's Google Images source)."""
    query = f"{title} {author} book cover".strip()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            resp = await c.get(
                "https://www.google.com/search",
                params={"q": query, "tbm": "isch", "tbs": "isz:m"},  # Medium size images
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            )
            if resp.status_code == 200:
                import re

                # Find image URLs in the response
                for m in re.finditer(r'"(https://[^"]+\.(?:jpg|jpeg|png))"', resp.text):
                    url = m.group(1)
                    if "gstatic" not in url and "google" not in url:
                        return url
    except Exception:
        pass
    return None


async def find_best_cover(isbn: str | None, title: str | None = None) -> dict[str, Any]:
    """Try all cover sources in parallel, return the best one."""
    import asyncio

    if not isbn:
        return {"url": None, "source": None}

    results = await asyncio.gather(
        apple_cover(isbn),
        bookcover_api(isbn),
        open_library_cover(isbn),
        google_images_cover(title or "", ""),
        return_exceptions=True,
    )

    sources = ["apple_books", "bookcover_api", "open_library", "google_images"]
    for url, source in zip(results, sources, strict=False):
        if isinstance(url, str) and url:
            return {"url": url, "source": source}

    return {"url": None, "source": None}
