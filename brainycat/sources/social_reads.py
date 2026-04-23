"""StoryGraph — moods, pace, content warnings, genre tags.

The only source for "mood" metadata. Valuable for taste engine.
Hardcover — modern Goodreads alternative with ratings and series.
"""

from __future__ import annotations

import re
from typing import Any

import httpx


async def search_storygraph(title: str, author: str = "") -> dict[str, Any] | None:
    """Search StoryGraph for mood/pace/content metadata."""
    query = f"{title} {author}".strip()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                f"https://app.thestorygraph.com/browse?search_term={query}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return None

            text = resp.text
            # Extract first result
            m = re.search(r'href="(/books/[^"]+)"', text)
            if not m:
                return None

            # Fetch book page
            book_resp = await client.get(
                f"https://app.thestorygraph.com{m.group(1)}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if book_resp.status_code != 200:
                return None

            page = book_resp.text
            result: dict[str, Any] = {"source": "storygraph"}

            # Moods
            moods = re.findall(r'class="[^"]*mood[^"]*"[^>]*>([^<]+)', page)
            if moods:
                result["moods"] = [m.strip() for m in moods[:5]]

            # Pace
            pace = re.search(r"(?:slow|medium|fast)\s*paced", page, re.IGNORECASE)
            if pace:
                result["pace"] = pace.group().strip()

            # Content warnings
            cw = re.findall(r"content-warning[^>]*>([^<]+)", page)
            if cw:
                result["content_warnings"] = [w.strip() for w in cw[:10]]

            # Genres/tags
            genres = re.findall(r'class="[^"]*genre-tag[^"]*"[^>]*>([^<]+)', page)
            if genres:
                result["genres"] = [g.strip() for g in genres[:10]]

            # Rating
            rating_m = re.search(r"(\d\.\d+)\s*/\s*5", page)
            if rating_m:
                result["rating"] = float(rating_m.group(1))

            return result if len(result) > 1 else None
    except Exception:
        return None


async def search_hardcover(title: str, author: str = "") -> dict[str, Any] | None:
    """Search Hardcover for metadata (modern Goodreads alternative)."""
    query = f"{title} {author}".strip()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Hardcover has a GraphQL API
            resp = await client.post(
                "https://hardcover.app/api/graphql",
                json={
                    "query": """query SearchBooks($query: String!) {
                        search(query: $query, first: 3) {
                            edges { node {
                                ... on Book { title slug rating ratingCount description
                                    authors { name }
                                    series { name position }
                                    tags { tag }
                                }
                            }}
                        }
                    }""",
                    "variables": {"query": query},
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            edges = data.get("data", {}).get("search", {}).get("edges", [])
            if not edges:
                return None

            node = edges[0].get("node", {})
            return {
                "source": "hardcover",
                "title": node.get("title"),
                "authors": [a.get("name") for a in node.get("authors", [])],
                "rating": node.get("rating"),
                "rating_count": node.get("ratingCount"),
                "description": (node.get("description") or "")[:500],
                "series": node.get("series", [{}])[0].get("name") if node.get("series") else None,
                "tags": [t.get("tag") for t in node.get("tags", [])[:10]],
            }
    except Exception:
        return None
