"""Open textbook and academic book sources.

OAPEN: 30K+ open access academic books (REST API)
DOAB: Directory of Open Access Books (OAI-PMH)
OpenStax: Free peer-reviewed college textbooks
Open Textbook Library: 1200+ faculty-reviewed textbooks
LibreTexts: Adaptable open textbooks
"""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client


async def search_oapen(query: str, limit: int = 20) -> dict[str, Any]:
    """Search OAPEN — 30K+ open access academic books."""
    try:
        client = get_client()
        resp = await client.get(
            "https://library.oapen.org/rest/search",
            params={"query": query, "expand": "metadata"},
        )
        if resp.status_code != 200:
            return {"books": []}
        data = resp.json()
        books = []
        for item in data if isinstance(data, list) else data.get("results", data.get("items", [])):
            meta = item.get("metadata", item) if isinstance(item, dict) else {}
            # OAPEN returns DSpace-style metadata
            title = _oapen_field(meta, "dc.title")
            author = _oapen_field(meta, "dc.contributor.author")
            isbn = _oapen_field(meta, "dc.identifier.isbn")
            desc = _oapen_field(meta, "dc.description.abstract")
            handle = item.get("handle", "")
            books.append(
                {
                    "source": "oapen",
                    "title": title,
                    "authors": [author] if author else [],
                    "language": _oapen_field(meta, "dc.language.iso"),
                    "isbn": isbn,
                    "description": (desc or "")[:300],
                    "url": f"https://library.oapen.org/handle/{handle}" if handle else "",
                    "download_url": f"https://library.oapen.org/bitstream/handle/{handle}" if handle else "",
                }
            )
            if len(books) >= limit:
                break
        return {"books": books}
    except Exception as e:
        return {"books": [], "error": str(e)[:100]}


def _oapen_field(meta: dict | list, key: str) -> str:
    """Extract a field from OAPEN DSpace metadata."""
    if isinstance(meta, list):
        for m in meta:
            if isinstance(m, dict) and m.get("key") == key:
                return m.get("value", "")
    elif isinstance(meta, dict):
        return meta.get(key, "")
    return ""


async def search_openstax(query: str = "", subject: str = "") -> dict[str, Any]:
    """Search OpenStax — free peer-reviewed college textbooks."""
    try:
        client = get_client()
        resp = await client.get(
            "https://openstax.org/apps/cms/api/v2/pages/",
            params={"type": "books.Book", "fields": "title,cover_url,description", "limit": 200},
        )
        if resp.status_code != 200:
            return {"books": []}
        data = resp.json()
        books = []
        for item in data.get("items", []):
            title = item.get("title", "")
            desc = item.get("description") or item.get("meta", {}).get("search_description", "") or ""
            if query and query.lower() not in title.lower() and query.lower() not in desc.lower():
                continue
            books.append(
                {
                    "source": "openstax",
                    "title": title,
                    "authors": ["OpenStax"],
                    "description": (item.get("description") or "")[:300],
                    "url": f"https://openstax.org/details/books/{item.get('slug', '')}",
                    "cover_url": item.get("cover_url"),
                    "subjects": item.get("subjects", []),
                }
            )
        return {"books": books}
    except Exception as e:
        return {"books": [], "error": str(e)[:100]}


async def search_open_textbook_library(query: str) -> dict[str, Any]:
    """Search Open Textbook Library — 1200+ faculty-reviewed textbooks."""
    try:
        client = get_client()
        resp = await client.get(f"https://open.umn.edu/opentextbooks/textbooks?search={query}", headers={"Accept": "text/html"})
        if resp.status_code != 200:
            return {"books": []}
        import re

        books = []
        for m in re.finditer(
            r'<a href="(/opentextbooks/textbooks/\d+)"[^>]*>\s*<h2[^>]*>([^<]+)</h2>.*?<p[^>]*class="[^"]*author[^"]*"[^>]*>([^<]*)</p>',
            resp.text,
            re.DOTALL,
        ):
            books.append(
                {
                    "source": "open_textbook_library",
                    "title": m.group(2).strip(),
                    "authors": [m.group(3).strip()] if m.group(3).strip() else [],
                    "url": f"https://open.umn.edu{m.group(1)}",
                }
            )
            if len(books) >= 20:
                break
        return {"books": books}
    except Exception as e:
        return {"books": [], "error": str(e)[:100]}
