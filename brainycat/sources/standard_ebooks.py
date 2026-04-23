"""Standard Ebooks — beautifully formatted public domain books.

https://standardebooks.org — ~800 books, all free, high-quality EPUB.
Better typography and formatting than Gutenberg.
"""

from __future__ import annotations

from typing import Any

import httpx

OPDS_URL = "https://standardebooks.org/feeds/opds"
SEARCH_URL = "https://standardebooks.org/ebooks"


async def search(query: str, limit: int = 20) -> dict[str, Any]:
    """Search Standard Ebooks catalog."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Standard Ebooks has an OPDS feed we can search
            resp = await client.get(f"{SEARCH_URL}?query={query}&per-page={limit}", headers={"Accept": "application/xml"})
            if resp.status_code != 200:
                return {"books": []}

            # Parse the HTML response for book links
            import re

            books = []
            for m in re.finditer(
                r'<a href="(/ebooks/[^"]+)"[^>]*>.*?<span[^>]*>([^<]+)</span>.*?<span[^>]*>([^<]+)</span>',
                resp.text,
                re.DOTALL,
            ):
                path, title, author = m.group(1), m.group(2).strip(), m.group(3).strip()
                books.append(
                    {
                        "source": "standard_ebooks",
                        "title": title,
                        "authors": [author],
                        "url": f"https://standardebooks.org{path}",
                        "epub_url": f"https://standardebooks.org{path}/downloads/epub",
                        "cover_url": f"https://standardebooks.org{path}/downloads/cover.jpg",
                    }
                )
                if len(books) >= limit:
                    break

            return {"books": books}
    except Exception:
        return {"books": []}
