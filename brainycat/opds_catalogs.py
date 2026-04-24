"""Pre-configured OPDS catalog subscriptions for free book discovery."""

from __future__ import annotations

from typing import Any

DEFAULT_CATALOGS = [
    {"id": "standard-ebooks", "name": "📚 Standard Ebooks", "url": "https://standardebooks.org/opds", "enabled": True},
    {"id": "gutenberg", "name": "📖 Project Gutenberg", "url": "https://m.gutenberg.org/ebooks.opds/", "enabled": True},
    {"id": "feedbooks", "name": "🇫🇷 Feedbooks Public Domain", "url": "https://feedbooks.com/publicdomain/catalog.atom", "enabled": True},
    {"id": "manybooks", "name": "📕 ManyBooks", "url": "https://manybooks.net/opds", "enabled": False},
    {"id": "oapen", "name": "🎓 OAPEN Academic", "url": "https://library.oapen.org/opds", "enabled": False},
    {"id": "gallica", "name": "🇫🇷 Gallica (BnF)", "url": "https://gallica.bnf.fr/opds", "enabled": False},
    {"id": "archive", "name": "📡 Internet Archive", "url": "https://bookserver.archive.org/catalog/", "enabled": False},
    {"id": "smashwords", "name": "✍️ Smashwords Free", "url": "https://www.smashwords.com/atom/free", "enabled": False},
]


async def get_catalogs() -> list[dict[str, Any]]:
    """Get catalog list with user overrides from DB."""
    from brainycat.db import fetch_all

    custom = await fetch_all("SELECT * FROM opds_subscriptions ORDER BY name")
    if custom:
        return [dict(r) for r in custom]
    return DEFAULT_CATALOGS


async def browse_opds(url: str, search: str | None = None) -> list[dict[str, Any]]:
    """Browse an OPDS catalog, optionally searching."""
    import re

    from brainycat.http_client import get_client

    client = get_client()
    target = url
    if search:
        # Try common OPDS search patterns
        target = f"{url}&query={search}" if "?" in url else f"{url}?query={search}"

    resp = await client.get(target, timeout=15, follow_redirects=True)
    if resp.status_code != 200:
        return []

    # Parse Atom/OPDS XML
    entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
    results = []
    for entry in entries[:50]:
        title = re.search(r"<title[^>]*>([^<]+)</title>", entry)
        author = re.search(r"<name>([^<]+)</name>", entry)
        summary = re.search(r"<(?:summary|content)[^>]*>([^<]+)</", entry)
        epub = re.search(r'href="([^"]+)"[^>]*type="application/epub\+zip"', entry)
        pdf = re.search(r'href="([^"]+)"[^>]*type="application/pdf"', entry)
        cover = re.search(r'href="([^"]+)"[^>]*rel="[^"]*image[^"]*"', entry)
        if not cover:
            cover = re.search(r'href="([^"]+)"[^>]*type="image/', entry)

        results.append(
            {
                "title": title.group(1).strip() if title else "",
                "author": author.group(1).strip() if author else "",
                "description": (summary.group(1).strip() if summary else "")[:300],
                "epub_url": epub.group(1) if epub else None,
                "pdf_url": pdf.group(1) if pdf else None,
                "cover_url": cover.group(1) if cover else None,
            }
        )
    return results
