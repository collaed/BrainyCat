"""Two-stage enrichment for hard-to-identify books.

Stage 1: LLM identifies the book (title cleanup, author extraction)
Stage 2: Structured APIs verify and fetch metadata (ISBN, description)

Used when standard enrichment fails (no ISBN, dirty title, low quality).
"""

from __future__ import annotations

from typing import Any

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client
from brainycat.llm_parse import parse_llm_json


async def deep_enrich(book_id: str) -> dict[str, Any]:
    """Two-stage enrichment for books that standard enrichment can't handle."""
    from uuid import UUID

    book = await fetch_one(
        "SELECT title, isbn, description, language, extra_metadata FROM books WHERE id = $1",
        UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    title = book["title"] or ""
    isbn = book["isbn"]
    result: dict[str, Any] = {"stages": []}

    # Stage 1: If title is dirty or no ISBN, ask LLM to identify the book
    if not isbn or _is_dirty_title(title):
        identified = await _llm_identify(title, book.get("language") or "eng")
        result["stages"].append({"stage": "llm_identify", **identified})

        if identified.get("clean_title"):
            from brainycat.metadata_audit import record_change

            await record_change(book_id, "title", title, identified["clean_title"], "deep_enrich_llm")
            await execute("UPDATE books SET title = $1, updated_at = now() WHERE id = $2", identified["clean_title"], UUID(book_id))
            title = identified["clean_title"]

        # Reject corporate/publisher names as authors
        _CORPORATE_NAMES = {
            "VMware",
            "Packt",
            "O'Reilly",
            "Microsoft",
            "Google",
            "Amazon",
            "Apress",
            "Manning",
            "Wiley",
            "Springer",
            "Elsevier",
            "Pearson",
            "McGraw-Hill",
        }
        if identified.get("author") and identified["author"] != "Unknown" and identified["author"] not in _CORPORATE_NAMES:
            # Link author
            author_row = await fetch_one(
                "INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = $1 RETURNING id",
                identified["author"],
            )
            if author_row:
                await execute(
                    "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    UUID(book_id),
                    author_row["id"],
                )

    # Stage 2: Search structured APIs with the clean title
    clean_title = title
    client = get_client()

    # 2a: Google Books (best fuzzy search)
    if not isbn:
        gb = await _search_google_books(client, clean_title)
        result["stages"].append({"stage": "google_books", **gb})
        if gb.get("isbn"):
            isbn = gb["isbn"]
            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
        if gb.get("description") and not book["description"]:
            await execute("UPDATE books SET description = $1 WHERE id = $2", gb["description"][:2000], UUID(book_id))
        if gb.get("pubdate") and not book.get("pubdate"):
            try:
                from dateutil.parser import parse as _dp

                await execute("UPDATE books SET pubdate = $1 WHERE id = $2", _dp(gb["pubdate"]), UUID(book_id))
            except Exception:
                pass

    # 2b: Open Library (good for editions/Work IDs)
    if isbn or clean_title:
        ol = await _search_open_library(client, isbn=isbn, title=clean_title)
        result["stages"].append({"stage": "open_library", **ol})
        if ol.get("isbn") and not isbn:
            isbn = ol["isbn"]
            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", isbn, UUID(book_id))
        if ol.get("description") and not book["description"]:
            await execute("UPDATE books SET description = $1 WHERE id = $2", ol["description"][:2000], UUID(book_id))

    result["final_isbn"] = isbn
    result["title"] = clean_title
    return result


def _is_dirty_title(title: str) -> bool:
    """Detect dirty titles that need LLM cleanup."""
    indicators = [
        " - libgen",
        "Anna's Archive",
        "(0)",
        "PP.",
        "OReilly.",
        "Apress.",
        " -- ",
        "libgen.li",
        "  ",
        "..",
        "_.pdf",
    ]
    return any(i in title for i in indicators) or title.startswith("[") or len(title) > 120


async def _llm_identify(dirty_title: str, language: str) -> dict[str, Any]:
    """Ask LLM to extract clean title and author from a dirty filename/title."""
    client = get_client()
    try:
        import asyncio

        async with asyncio.timeout(15):
            resp = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={
                    "model": "llama-3.3-70b-versatile",
                    "task_hint": "classification",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Extract the clean book title and author from this dirty string. "
                            f'Reply ONLY with JSON: {{"title": "...", "author": "..."}}\n\n'
                            f"Dirty: {dirty_title}",
                        }
                    ],
                    "max_tokens": 100,
                    "temperature": 0,
                },
            )
        if resp.status_code == 200:
            text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = parse_llm_json(text)
            if parsed and isinstance(parsed, dict):
                return {
                    "clean_title": parsed.get("title", ""),
                    "author": parsed.get("author", ""),
                }
    except Exception:
        pass
    return {}


async def _search_google_books(client: Any, title: str) -> dict[str, Any]:
    """Search Google Books with fuzzy title matching."""
    import asyncio

    from brainycat.rate_limit import rate_limiter

    try:
        await rate_limiter.wait("google")
        async with asyncio.timeout(10):
            resp = await client.get(
                "https://www.googleapis.com/books/v1/volumes",
                params={"q": title, "maxResults": 3},
            )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                vi = items[0].get("volumeInfo", {})
                isbns = vi.get("industryIdentifiers", [])
                isbn13 = next((i["identifier"] for i in isbns if i.get("type") == "ISBN_13"), None)
                isbn10 = next((i["identifier"] for i in isbns if i.get("type") == "ISBN_10"), None)
                return {
                    "isbn": isbn13 or isbn10,
                    "title": vi.get("title"),
                    "author": ", ".join(vi.get("authors", [])),
                    "description": vi.get("description", ""),
                    "pubdate": vi.get("publishedDate"),
                    "categories": vi.get("categories", []),
                }
        elif resp.status_code == 429:
            await rate_limiter.record_failure("google")
    except Exception:
        pass
    return {}


async def _search_open_library(client: Any, isbn: str | None = None, title: str = "") -> dict[str, Any]:
    """Search Open Library by ISBN or title."""
    import asyncio

    from brainycat.rate_limit import rate_limiter

    try:
        await rate_limiter.wait("openlibrary")
        if isbn:
            async with asyncio.timeout(10):
                resp = await client.get(f"https://openlibrary.org/isbn/{isbn}.json")
            if resp.status_code == 200:
                data = resp.json()
                desc = data.get("description")
                if isinstance(desc, dict):
                    desc = desc.get("value", "")
                return {"isbn": isbn, "description": desc or "", "ol_key": data.get("key")}

        if title:
            async with asyncio.timeout(10):
                resp = await client.get(
                    "https://openlibrary.org/search.json",
                    params={"title": title, "limit": 1},
                )
            if resp.status_code == 200:
                docs = resp.json().get("docs", [])
                if docs:
                    doc = docs[0]
                    return {
                        "isbn": (doc.get("isbn") or [None])[0],
                        "title": doc.get("title"),
                        "author": ", ".join(doc.get("author_name", [])),
                        "description": "",
                        "ol_key": doc.get("key"),
                    }
    except Exception:
        pass
    return {}
