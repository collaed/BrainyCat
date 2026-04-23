"""Hardcover.app API — community-curated book metadata via GraphQL."""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client

API_URL = "https://hardcover.app/api/graphql"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Hardcover via GraphQL."""
    if isbn:
        query_str = isbn
    elif title:
        query_str = title
    else:
        return None

    graphql = {
        "query": """
        query SearchBooks($query: String!) {
            search(query: $query, query_type: "books", per_page: 1) {
                results {
                    ... on Book {
                        title
                        description
                        image { url }
                        contributions { author { name } }
                        genres { genre { name } }
                        release_year
                        pages
                        isbn_13
                    }
                }
            }
        }
        """,
        "variables": {"query": query_str},
    }

    try:
        headers = {}
        import os

        key = os.environ.get("HARDCOVER_API_KEY", "")
        if key:
            headers["Authorization"] = key if key.startswith("Bearer") else f"Bearer {key}"
        client = get_client()
        resp = await client.post(API_URL, json=graphql)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    results = data.get("data", {}).get("search", {}).get("results", [])
    if not results:
        return None

    book = results[0]
    authors = [c.get("author", {}).get("name") for c in book.get("contributions", []) if c.get("author")]
    genres = [g.get("genre", {}).get("name") for g in book.get("genres", []) if g.get("genre")]
    image = book.get("image", {})

    return {
        "source": "hardcover",
        "title": book.get("title"),
        "description": book.get("description"),
        "isbn": book.get("isbn_13"),
        "language": None,
        "publisher": None,
        "pubdate": str(book.get("release_year", "")),
        "genres": genres,
        "cover_url": image.get("url") if image else None,
        "authors": authors,
        "pages": book.get("pages"),
    }
