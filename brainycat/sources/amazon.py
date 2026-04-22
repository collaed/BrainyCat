"""Amazon metadata source — scrape product pages for book metadata."""

from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.amazon.com/s"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Amazon for book metadata."""
    query = isbn or title
    if not query:
        return None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
            # Search Amazon books
            resp = await client.get(SEARCH_URL, params={"k": query, "i": "stripbooks-intl-ship", "s": "relevanceblender"})
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find first result
            result = soup.select_one('[data-component-type="s-search-result"]')
            if not result:
                return None

            # Extract title
            title_el = result.select_one("h2 a span")
            book_title = title_el.text.strip() if title_el else None

            # Extract author
            author_el = result.select_one(".a-row .a-size-base+ .a-size-base")
            author = author_el.text.strip() if author_el else None

            # Extract ASIN from link
            link = result.select_one("h2 a")
            asin = None
            if link and link.get("href"):
                import re

                m = re.search(r"/dp/([A-Z0-9]{10})", link["href"])
                if m:
                    asin = m.group(1)

            # Extract cover image
            img = result.select_one("img.s-image")
            cover_url = img["src"] if img and img.get("src") else None

            # Extract rating
            rating_el = result.select_one(".a-icon-alt")
            rating = None
            if rating_el:
                import re

                m = re.search(r"([\d.]+) out of", rating_el.text)
                if m:
                    rating = float(m.group(1))

            if not book_title:
                return None

            return {
                "source": "amazon",
                "title": book_title,
                "description": None,  # Would need product page fetch
                "isbn": isbn,
                "language": None,
                "publisher": None,
                "pubdate": None,
                "genres": [],
                "cover_url": cover_url,
                "authors": [author] if author else [],
                "rating": rating,
                "asin": asin,
            }
    except Exception:
        return None
