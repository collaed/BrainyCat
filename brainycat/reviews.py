"""Review aggregation — 7 sources for ratings and reviews.

Sources: Google Books, Open Library, Hardcover, StoryGraph, Audnexus, Goodreads (web), Wikidata
Aggregation: weighted average (sources with more ratings get more weight).
"""

from __future__ import annotations

import re
from typing import Any

from brainycat.http_client import get_client


async def aggregate_reviews(title: str, isbn: str = "", author: str = "") -> dict[str, Any]:
    """Fetch ratings from all available sources, return weighted average."""
    import asyncio

    results = await asyncio.gather(
        _google_books_rating(isbn or title),
        _open_library_rating(isbn),
        _hardcover_rating(title, author),
        _storygraph_rating(title, author),
        _audnexus_rating(isbn),
        return_exceptions=True,
    )

    sources = ["google_books", "open_library", "hardcover", "storygraph", "audnexus"]
    ratings = []
    source_data = {}

    for src, result in zip(sources, results, strict=False):
        if isinstance(result, dict) and result.get("rating"):
            ratings.append({"source": src, "rating": result["rating"], "count": result.get("count", 0)})
            source_data[src] = result

    if not ratings:
        return {"average": None, "sources": 0}

    # Weighted average: sources with more ratings get more weight
    total_weight = sum(max(r["count"], 1) for r in ratings)
    weighted = sum(r["rating"] * max(r["count"], 1) for r in ratings) / total_weight

    return {
        "average": round(weighted, 2),
        "sources": len(ratings),
        "ratings": ratings,
    }


async def _google_books_rating(query: str) -> dict[str, Any]:
    try:
        c = get_client()
        r = await c.get(f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=1")
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items:
                vi = items[0]["volumeInfo"]
                return {"rating": vi.get("averageRating"), "count": vi.get("ratingsCount", 0)}
    except Exception:
        pass
    return {}


async def _open_library_rating(isbn: str) -> dict[str, Any]:
    if not isbn:
        return {}
    try:
        c = get_client()
        # Find work ID
        r = await c.get(f"https://openlibrary.org/isbn/{isbn}.json")
        if r.status_code == 200:
            work_key = r.json().get("works", [{}])[0].get("key", "")
            if work_key:
                r2 = await c.get(f"https://openlibrary.org{work_key}/ratings.json")
                if r2.status_code == 200:
                    s = r2.json().get("summary", {})
                    return {"rating": s.get("average"), "count": s.get("count", 0)}
    except Exception:
        pass
    return {}


async def _hardcover_rating(title: str, author: str) -> dict[str, Any]:
    try:
        c = get_client()
        r = await c.post(
            "https://hardcover.app/api/graphql",
            json={
                "query": "query($q:String!){search(query:$q,first:1){edges{node{...on Book{rating ratingCount}}}}}",
                "variables": {"query": f"{title} {author}".strip()},
            },
            headers={"Content-Type": "application/json"},
        )
        if r.status_code == 200:
            edges = r.json().get("data", {}).get("search", {}).get("edges", [])
            if edges:
                node = edges[0]["node"]
                return {"rating": node.get("rating"), "count": node.get("ratingCount", 0)}
    except Exception:
        pass
    return {}


async def _storygraph_rating(title: str, author: str) -> dict[str, Any]:
    try:
        c = get_client()
        r = await c.get(f"https://app.thestorygraph.com/browse?search_term={title} {author}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r"(\d\.\d+)\s*/\s*5", r.text)
            if m:
                return {"rating": float(m.group(1)), "count": 0}
    except Exception:
        pass
    return {}


async def _audnexus_rating(isbn: str) -> dict[str, Any]:
    """Audnexus — audiobook ratings from Audible."""
    if not isbn:
        return {}
    try:
        c = get_client()
        r = await c.get(f"https://api.audnex.us/books/{isbn}")
        if r.status_code == 200:
            data = r.json()
            return {"rating": data.get("rating"), "count": data.get("ratingCount", 0)}
    except Exception:
        pass
    return {}
