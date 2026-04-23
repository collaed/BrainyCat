"""Open Library enhanced — Works API + Ratings API for richer metadata."""

from __future__ import annotations

from typing import Any

import httpx

BASE = "https://openlibrary.org"


async def get_work_details(work_id: str) -> dict[str, Any] | None:
    """Get rich metadata from OL Works API (subjects, related editions, descriptions)."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(f"{BASE}/works/{work_id}.json")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return {
                "subjects": data.get("subjects", []),
                "subject_places": data.get("subject_places", []),
                "subject_times": data.get("subject_times", []),
                "subject_people": data.get("subject_people", []),
                "description": data.get("description", {}).get("value", "")
                if isinstance(data.get("description"), dict)
                else str(data.get("description", "")),
                "first_publish_date": data.get("first_publish_date"),
                "covers": [f"https://covers.openlibrary.org/b/id/{c}-L.jpg" for c in (data.get("covers") or [])[:3]],
            }
    except Exception:
        return None


async def get_work_ratings(work_id: str) -> dict[str, Any] | None:
    """Get community ratings from OL Ratings API."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(f"{BASE}/works/{work_id}/ratings.json")
            if resp.status_code != 200:
                return None
            data = resp.json()
            summary = data.get("summary", {})
            return {
                "average": summary.get("average"),
                "count": summary.get("count"),
            }
    except Exception:
        return None


async def search_enhanced(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Enhanced OL search — gets work details + ratings in addition to basic search."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            params = {}
            if isbn:
                params["isbn"] = isbn
            elif title:
                params["title"] = title
            else:
                return None
            resp = await client.get(f"{BASE}/search.json", params={**params, "limit": 3})
            if resp.status_code != 200:
                return None
            data = resp.json()
            docs = data.get("docs", [])
            if not docs:
                return None

            doc = docs[0]
            result: dict[str, Any] = {
                "title": doc.get("title"),
                "authors": list(doc.get("author_name", [])),
                "isbn": (doc.get("isbn") or [None])[0],
                "publisher": (doc.get("publisher") or [None])[0],
                "publish_year": doc.get("first_publish_year"),
                "page_count": doc.get("number_of_pages_median"),
                "language": (doc.get("language") or [None])[0],
                "cover_url": f"https://covers.openlibrary.org/b/olid/{doc['cover_edition_key']}-L.jpg"
                if doc.get("cover_edition_key")
                else None,
            }

            # Enrich with Works API
            work_key = doc.get("key")
            if work_key:
                work = await get_work_details(work_key.replace("/works/", ""))
                if work:
                    result["subjects"] = work.get("subjects", [])[:10]
                    result["subject_people"] = work.get("subject_people", [])
                    if work.get("description"):
                        result["description"] = work["description"][:500]
                    if work.get("covers"):
                        result["cover_url"] = result.get("cover_url") or work["covers"][0]

                # Get ratings
                ratings = await get_work_ratings(work_key.replace("/works/", ""))
                if ratings and ratings.get("average"):
                    result["rating"] = ratings["average"]
                    result["rating_count"] = ratings["count"]

            return result
    except Exception:
        return None
