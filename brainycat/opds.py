"""OPDS 1.2 catalog feed."""

from __future__ import annotations

from typing import Any

from fastapi.responses import Response

from brainycat.db import fetch_all

OPDS_NS = "http://www.w3.org/2005/Atom"
OPDS_CAT = "http://opds-spec.org/2010/catalog"


async def catalog() -> Response:
    """Root OPDS catalog."""
    books = await fetch_all("""
        SELECT b.id, b.title, b.description, b.updated_at,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        GROUP BY b.id ORDER BY b.updated_at DESC LIMIT 100
    """)
    entries = "\n".join(_entry(b) for b in books)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="{OPDS_NS}" xmlns:opds="{OPDS_CAT}">
  <id>urn:brainycat:catalog</id>
  <title>BrainyCat Library</title>
  <updated>{books[0]["updated_at"].isoformat() if books else ""}</updated>
  <link rel="self" href="/api/v1/opds/catalog.xml" type="application/atom+xml;profile=opds-catalog"/>
  <link rel="search" href="/api/v1/opds/search?q={{searchTerms}}" type="application/atom+xml"/>
  {entries}
</feed>"""
    return Response(content=xml, media_type="application/atom+xml;profile=opds-catalog")


async def search_opds(q: str) -> Response:
    """OPDS search."""
    books = await fetch_all(
        """
        SELECT b.id, b.title, b.description, b.updated_at,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.search_vector @@ plainto_tsquery('simple', unaccent($1)) OR similarity(b.title, $1) > 0.3
        GROUP BY b.id ORDER BY b.updated_at DESC LIMIT 50
    """,
        q,
    )
    entries = "\n".join(_entry(b) for b in books)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="{OPDS_NS}"><id>urn:brainycat:search:{q}</id><title>Search: {q}</title>{entries}</feed>"""
    return Response(content=xml, media_type="application/atom+xml;profile=opds-catalog")


def _entry(b: Any) -> str:
    authors_xml = "".join(f"<author><name>{a}</name></author>" for a in (b["authors"] or []))
    return f"""<entry>
  <id>urn:brainycat:book:{b["id"]}</id>
  <title>{b["title"]}</title>
  {authors_xml}
  <summary>{b["description"] or ""}</summary>
  <updated>{b["updated_at"].isoformat() if b["updated_at"] else ""}</updated>
  <link rel="http://opds-spec.org/acquisition" href="/api/v1/books/{b["id"]}/file/epub" type="application/epub+zip"/>
  <link rel="http://opds-spec.org/image" href="/api/v1/books/{b["id"]}/cover" type="image/jpeg"/>
</entry>"""
