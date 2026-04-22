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
    """Search for a book on Amazon via Google across multiple country domains."""
    query = isbn or title
    if not query:
        return None

    # Try multiple Amazon domains — more chances of finding metadata
    domains = ["amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.es", "amazon.it"]
    results: list[dict[str, Any]] = []

    for domain in domains:
        google_query = f"site:{domain} {query} book"
        product_url = await _google_find_amazon_url(google_query, domain)
        if product_url:
            data = await _scrape_product_page(product_url)
            if data:
                data["_source_domain"] = domain
                results.append(data)
                break  # Got a result, stop trying other domains

    if not results:
        # Fallback: direct Amazon search
        product_url = await _amazon_search(query)
        if product_url:
            data = await _scrape_product_page(product_url)
            if data:
                return data
        return None

    # If we got results from multiple domains, merge (best cover, longest description)
    if len(results) == 1:
        return results[0]

    best = results[0]
    for r in results[1:]:
        if len(r.get("description", "")) > len(best.get("description", "")):
            best["description"] = r["description"]
        if r.get("cover_url") and not best.get("cover_url"):
            best["cover_url"] = r["cover_url"]
        if r.get("series") and not best.get("series"):
            best["series"] = r["series"]
    return best


def _ipv6_transport() -> httpx.AsyncHTTPTransport:
    """Create transport preferring IPv6 — harder to range-block."""
    return httpx.AsyncHTTPTransport(local_address="::" if socket.has_ipv6 else "0.0.0.0")


async def _google_find_amazon_url(query: str, domain: str = "amazon.com") -> str | None:
    """Use Google to find an Amazon product page on a specific domain."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, transport=_ipv6_transport()) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": 5},
                headers={"User-Agent": _next_ua()},
            )
            if resp.status_code != 200:
                return None
            # Find Amazon dp/ URLs in results for the target domain
            escaped = re.escape(domain)
            for m in re.finditer(rf"https?://www\.{escaped}/[^\"&]+/dp/[A-Z0-9]{{10}}", resp.text):
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

        # Series info from title or detail bullets
        series_name = None
        series_index = None
        if book_title:
            m = re.search(r"\((.+?)\s+Book\s+(\d+)\)", book_title)
            if m:
                series_name = m.group(1).strip()
                series_index = int(m.group(2))
                book_title = re.sub(r"\s*\(.+?Book\s+\d+\)", "", book_title).strip()
        # Also check detail bullets for series
        for row in soup.select("#detailBullets_feature_div li, #seriesBulletWidget span"):
            text = row.text.strip()
            m = re.search(r"Book\s+(\d+)\s+of\s+\d+\s*:\s*(.+)", text)
            if m and not series_name:
                series_index = int(m.group(1))
                series_name = m.group(2).strip()

        if not book_title:
            return None

        return {
            "source": "amazon",
            "series": series_name,
            "series_index": series_index,
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
