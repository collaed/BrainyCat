"""isbntools integration — evaluate against our custom ISBN code.

Provides metadata lookup via isbntools' plugin system.
Runs side-by-side with our existing enrichment for comparison.

Config: BRAINYCAT_EXP_ISBNTOOLS=1
"""

from __future__ import annotations

from typing import Any


async def lookup_isbn(isbn: str) -> dict[str, Any]:
    """Fetch metadata via Open Library ISBN API (isbnlib replacement)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://openlibrary.org/isbn/{isbn}.json")
            if r.status_code != 200:
                return {"source": "openlibrary_isbn", "found": False}
            data = r.json()
            # Get work for authors
            authors = []
            for a in data.get("authors", []):
                ar = await client.get(f"https://openlibrary.org{a['key']}.json")
                if ar.status_code == 200:
                    authors.append(ar.json().get("name", ""))
    except Exception:
        return {"source": "openlibrary_isbn", "found": False}

    return {
        "source": "openlibrary_isbn",
        "found": True,
        "title": data.get("title", ""),
        "authors": authors,
        "publisher": (data.get("publishers") or [""])[0],
        "year": data.get("publish_date", ""),
        "pages": data.get("number_of_pages"),
    }


async def compare_with_existing(book_id: str, isbn: str) -> dict[str, Any]:
    """Run isbntools lookup and compare with what we already have."""
    from brainycat.db import fetch_one

    book = await fetch_one("SELECT title, author, publisher FROM books WHERE id = $1", book_id)
    isbntools_result = await lookup_isbn(isbn)

    if not isbntools_result["found"]:
        return {"match": None, "isbntools": isbntools_result}

    our_title = (book["title"] or "").lower().strip() if book else ""
    their_title = isbntools_result["title"].lower().strip()
    title_match = our_title == their_title or our_title in their_title or their_title in our_title

    return {
        "match": title_match,
        "ours": {"title": book["title"] if book else None},
        "isbntools": isbntools_result,
    }
