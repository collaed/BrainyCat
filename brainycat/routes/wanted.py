"""Wanted books — public list for acquisition tools (Bookshelf, Readarr forks).

No auth on GET (so external tools can poll).
Auth required to add/remove.
Enriched with ISBN, author, and external links for best matching.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from brainycat import db
from brainycat.auth import get_current_user

router = APIRouter(prefix="/api/v1/wanted", tags=["wanted"])


@router.get("")
async def list_wanted(format: str = Query("json")) -> Any:
    """Public wanted list — no auth. Pollable by Bookshelf/Readarr."""
    rows = await db.fetch_all(
        """SELECT w.id, w.title, w.author, w.isbn, w.asin,
                  w.goodreads_url, w.amazon_url, w.notes, w.priority, w.created_at
           FROM wanted_books w ORDER BY w.priority DESC, w.created_at DESC"""
    )
    books = [dict(r) for r in rows]

    if format == "opds":
        # OPDS acquisition feed (some tools prefer this)
        from fastapi.responses import Response

        items = "\n".join(
            f"""<entry>
  <title>{b["title"]}</title>
  <author><name>{b["author"] or ""}</name></author>
  <id>urn:isbn:{b["isbn"]}</id>
  <dc:identifier>isbn:{b["isbn"]}</dc:identifier>
</entry>"""
            for b in books
            if b.get("isbn")
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <title>BrainyCat Wanted Books</title>
  <id>urn:brainycat:wanted</id>
  {items}
</feed>"""
        return Response(content=xml, media_type="application/atom+xml")

    return books


@router.post("")
async def add_wanted(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add a book to the wanted list. Auto-enriches with ISBN and links."""
    title = body.get("title", "")
    author = body.get("author", "")
    isbn = body.get("isbn", "")
    notes = body.get("notes", "")
    priority = body.get("priority", 5)

    # Auto-enrich: find ISBN and links if not provided
    if not isbn and title:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            # Try Google Books
            q = f"{title} {author}".strip()
            r = await client.get(f"https://www.googleapis.com/books/v1/volumes?q={q}&maxResults=1")
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    info = items[0].get("volumeInfo", {})
                    if not isbn:
                        for ident in info.get("industryIdentifiers", []):
                            if ident["type"] == "ISBN_13":
                                isbn = ident["identifier"]
                                break
                    if not author:
                        author = (info.get("authors") or [""])[0]

    # Build Amazon search URL for acquisition tools
    amazon_url = f"https://www.amazon.com/s?k={title.replace(' ', '+')}+{author.replace(' ', '+')}" if title else ""
    goodreads_url = f"https://www.goodreads.com/search?q={isbn or title.replace(' ', '+')}" if (isbn or title) else ""

    row = await db.fetch_one(
        """INSERT INTO wanted_books (title, author, isbn, amazon_url, goodreads_url, notes, priority)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
        title,
        author,
        isbn or None,
        amazon_url,
        goodreads_url,
        notes,
        priority,
    )
    return {"id": str(row["id"]), "title": title, "isbn": isbn, "amazon_url": amazon_url}


@router.delete("/{wanted_id}")
async def remove_wanted(wanted_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Remove from wanted list (e.g., after acquisition)."""
    await db.execute("DELETE FROM wanted_books WHERE id = $1", UUID(wanted_id))
    return {"ok": True}


@router.post("/from-book/{book_id}")
async def want_similar(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add books similar to one you have (same author, next in series)."""
    book = await db.fetch_one(
        """SELECT b.title, a.name as author, b.isbn FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE b.id = $1""",
        UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    # Search for other books by same author
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"https://www.googleapis.com/books/v1/volumes?q=inauthor:{book['author']}&maxResults=5")
        suggestions = []
        if r.status_code == 200:
            for item in r.json().get("items", []):
                info = item.get("volumeInfo", {})
                t = info.get("title", "")
                # Skip if we already have it
                existing = await db.fetch_one("SELECT id FROM books WHERE title ILIKE $1", f"%{t[:30]}%")
                if not existing and t:
                    suggestions.append({"title": t, "author": book["author"]})

    return {"suggestions": suggestions[:5], "based_on": book["title"]}
