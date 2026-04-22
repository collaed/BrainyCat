"""Amazon metadata — via search engine proxy (Calibre's approach) + direct product pages."""

from __future__ import annotations

import re
import socket
from typing import Any

import httpx
from bs4 import BeautifulSoup

# Rotate user agents like Calibre does
_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
]
_ua_idx = 0


def _next_ua() -> str:
    global _ua_idx
    _ua_idx = (_ua_idx + 1) % len(_UA_LIST)
    return _UA_LIST[_ua_idx]


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search for a book on Amazon via Google (Calibre's approach)."""
    query = isbn or title
    if not query:
        return None

    # Step 1: Find Amazon product URL via Google
    google_query = f"site:amazon.com {query} book"
    product_url = await _google_find_amazon_url(google_query)

    if not product_url:
        # Fallback: direct Amazon search
        product_url = await _amazon_search(query)

    if not product_url:
        return None

    # Step 2: Scrape the product page
    return await _scrape_product_page(product_url)


def _ipv6_transport() -> httpx.AsyncHTTPTransport:
    """Create transport preferring IPv6 — harder to range-block."""
    return httpx.AsyncHTTPTransport(local_address="::" if socket.has_ipv6 else "0.0.0.0")


async def _google_find_amazon_url(query: str) -> str | None:
    """Use Google to find an Amazon product page."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, transport=_ipv6_transport()) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": 5},
                headers={"User-Agent": _next_ua()},
            )
            if resp.status_code != 200:
                return None
            # Find Amazon dp/ URLs in results
            for m in re.finditer(r"https?://www\.amazon\.\w+/[^\"&]+/dp/[A-Z0-9]{10}", resp.text):
                return m.group()
    except Exception:
        pass
    return None


async def _amazon_search(query: str) -> str | None:
    """Direct Amazon search as fallback."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, transport=_ipv6_transport()) as client:
            resp = await client.get(
                "https://www.amazon.com/s",
                params={"k": query, "i": "stripbooks-intl-ship"},
                headers={"User-Agent": _next_ua(), "Accept-Language": "en-US,en;q=0.9"},
            )
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            link = soup.select_one('[data-component-type="s-search-result"] h2 a')
            if link and link.get("href"):
                href = link["href"]
                if "/dp/" in href:
                    return "https://www.amazon.com" + href if href.startswith("/") else href
    except Exception:
        pass
    return None


async def _scrape_product_page(url: str) -> dict[str, Any] | None:
    """Scrape an Amazon product page for metadata."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, transport=_ipv6_transport()) as client:
            resp = await client.get(url, headers={"User-Agent": _next_ua(), "Accept-Language": "en-US,en;q=0.9"})
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")

        # Title
        title_el = soup.select_one("#productTitle, #ebooksProductTitle")
        book_title = title_el.text.strip() if title_el else None

        # Author
        author_el = soup.select_one(".author a, #bylineInfo .author a")
        author = author_el.text.strip() if author_el else None

        # Description
        desc_el = soup.select_one("#bookDescription_feature_div noscript, #bookDescription_feature_div span")
        description = desc_el.text.strip()[:2000] if desc_el else None

        # Cover
        img = soup.select_one("#imgBlkFront, #ebooksImgBlkFront, #main-image")
        cover_url = None
        if img:
            cover_url = img.get("data-a-dynamic-image", img.get("src", ""))
            if "{" in cover_url:
                # data-a-dynamic-image is JSON — pick largest
                m = re.findall(r'"(https://[^"]+)"', cover_url)
                cover_url = m[-1] if m else None

        # ASIN
        asin = re.search(r"/dp/([A-Z0-9]{10})", url)
        asin = asin.group(1) if asin else None

        # ISBN from detail table
        isbn = None
        for row in soup.select("#detailBullets_feature_div li, #productDetailsTable .content li"):
            text = row.text
            if "ISBN-13" in text or "ISBN-10" in text:
                m = re.search(r"97[89][\d-]{10,}", text)
                if m:
                    isbn = re.sub(r"[^0-9]", "", m.group())

        # Rating
        rating = None
        rating_el = soup.select_one("#acrPopover .a-icon-alt, .reviewCountTextLinkedHistogram .a-icon-alt")
        if rating_el:
            m = re.search(r"([\d.]+)", rating_el.text)
            if m:
                rating = float(m.group(1))

        # Categories/genres
        genres = [a.text.strip() for a in soup.select("#wayfinding-breadcrumbs_feature_div a") if a.text.strip()]

        # Publisher + date from details
        publisher = None
        pubdate = None
        for row in soup.select("#detailBullets_feature_div li, #productDetailsTable .content li"):
            text = row.text.strip()
            if "Publisher" in text:
                m = re.search(r":\s*(.+?)(?:\(|$)", text)
                if m:
                    publisher = m.group(1).strip()
                m2 = re.search(r"\(([^)]+)\)", text)
                if m2:
                    pubdate = m2.group(1)

        if not book_title:
            return None

        return {
            "source": "amazon",
            "title": book_title,
            "description": description,
            "isbn": isbn,
            "language": None,
            "publisher": publisher,
            "pubdate": pubdate,
            "genres": genres,
            "cover_url": cover_url,
            "authors": [author] if author else [],
            "rating": rating,
            "asin": asin,
        }
    except Exception:
        return None


async def search_by_text_quotes(quotes: list[str]) -> dict[str, Any] | None:
    """Search Google with text quotes from the book to identify it."""
    if not quotes:
        return None
    # Use 2-3 short quotes in Google search
    query = " ".join(f'"{q[:80]}"' for q in quotes[:3]) + " book"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, transport=_ipv6_transport()) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": 5},
                headers={"User-Agent": _next_ua()},
            )
            if resp.status_code != 200:
                return None
            # Look for Amazon, Goodreads, or Google Books links
            for m in re.finditer(r"https?://www\.amazon\.\w+/[^\"&]+/dp/[A-Z0-9]{10}", resp.text):
                return await _scrape_product_page(m.group())
            # Look for Google Books
            for m in re.finditer(r"https?://books\.google\.\w+/books\?id=([^\"&]+)", resp.text):
                return {"source": "google_quote_match", "google_books_id": m.group(1)}
    except Exception:
        pass
    return None
