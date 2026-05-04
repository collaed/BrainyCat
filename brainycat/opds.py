"""OPDS 1.2 catalog feed with pagination, facets, and search."""

from __future__ import annotations

from typing import Any

from fastapi.responses import Response

from brainycat.db import fetch_all, fetch_one

NS = "http://www.w3.org/2005/Atom"
OPDS = "http://opds-spec.org/2010/catalog"
PAGE_SIZE = 50


async def catalog(page: int = 1) -> Response:
    offset = (page - 1) * PAGE_SIZE
    total = await fetch_one("SELECT count(*) as n FROM books")
    total_count = total["n"] if total else 0

    books = await fetch_all(f"""
        SELECT b.id, b.title, b.description, b.isbn, b.updated_at, b.page_count, b.estimated_reading_minutes, b.quality_score,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT bf.format) FILTER (WHERE bf.format IS NOT NULL) as formats
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN book_files bf ON bf.book_id = b.id
        GROUP BY b.id ORDER BY b.updated_at DESC
        LIMIT {PAGE_SIZE} OFFSET {offset}
    """)

    entries = "\n".join(_entry(b) for b in books)
    has_next = offset + PAGE_SIZE < total_count
    has_prev = page > 1

    nav = ""
    if has_next:
        nav += f'<link rel="next" href="/api/v1/opds/catalog.xml?page={page + 1}" type="application/atom+xml;profile=opds-catalog"/>'
    if has_prev:
        nav += f'<link rel="previous" href="/api/v1/opds/catalog.xml?page={page - 1}" type="application/atom+xml;profile=opds-catalog"/>'

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="{NS}" xmlns:opds="{OPDS}" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <id>urn:brainycat:catalog:page:{page}</id>
  <title>BrainyCat Library</title>
  <updated>{books[0]["updated_at"].isoformat() if books else ""}</updated>
  <link rel="self" href="/api/v1/opds/catalog.xml?page={page}" type="application/atom+xml;profile=opds-catalog"/>
  <link rel="start" href="/api/v1/opds/catalog.xml" type="application/atom+xml;profile=opds-catalog"/>
  <link rel="search" href="/api/v1/opds/search?q={{searchTerms}}" type="application/atom+xml"/>
  {nav}
  <opensearch:totalResults>{total_count}</opensearch:totalResults>
  <opensearch:startIndex>{offset + 1}</opensearch:startIndex>
  <opensearch:itemsPerPage>{PAGE_SIZE}</opensearch:itemsPerPage>
  {entries}
</feed>"""
    return Response(content=xml, media_type="application/atom+xml;profile=opds-catalog")


async def search_opds(q: str, page: int = 1) -> Response:
    offset = (page - 1) * PAGE_SIZE
    books = await fetch_all(
        f"""
        SELECT b.id, b.title, b.description, b.isbn, b.updated_at, b.page_count, b.estimated_reading_minutes, b.quality_score,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT bf.format) FILTER (WHERE bf.format IS NOT NULL) as formats
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN book_files bf ON bf.book_id = b.id
        WHERE b.title ILIKE '%' || $1 || '%'
           OR EXISTS (SELECT 1 FROM books_authors ba2 JOIN authors a2 ON a2.id = ba2.author_id WHERE ba2.book_id = b.id AND a2.name ILIKE '%' || $1 || '%')
        GROUP BY b.id ORDER BY b.updated_at DESC
        LIMIT {PAGE_SIZE} OFFSET {offset}
    """,
        q,
    )

    entries = "\n".join(_entry(b) for b in books)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="{NS}"><id>urn:brainycat:search:{q}:{page}</id><title>Search: {q}</title>
<link rel="self" href="/api/v1/opds/search?q={q}&amp;page={page}" type="application/atom+xml;profile=opds-catalog"/>
{entries}</feed>"""
    return Response(content=xml, media_type="application/atom+xml;profile=opds-catalog")


def _entry(b: Any) -> str:
    authors_xml = "".join(f"<author><name>{_esc(a)}</name></author>" for a in (b["authors"] or []))
    formats = b["formats"] or []

    # Acquisition links for each format
    acq_links = ""
    mime_map = {"epub": "application/epub+zip", "pdf": "application/pdf", "mobi": "application/x-mobipocket-ebook"}
    for fmt in formats:
        mime = mime_map.get(fmt, "application/octet-stream")
        acq_links += f'<link rel="http://opds-spec.org/acquisition" href="/api/v1/books/{b["id"]}/file/{fmt}" type="{mime}"/>\n'

    return f"""<entry>
  <id>urn:brainycat:book:{b["id"]}</id>
  <title>{_esc(b["title"])}</title>
  {authors_xml}
  <summary>{_esc((b["description"] or "")[:500])}</summary>
  <updated>{b["updated_at"].isoformat() if b["updated_at"] else ""}</updated>
  {f'<dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/">{b["isbn"]}</dc:identifier>' if b.get("isbn") else ""}
  <link rel="http://opds-spec.org/image" href="/api/v1/books/{b["id"]}/cover" type="image/jpeg"/>
  <link rel="http://opds-spec.org/image/thumbnail" href="/api/v1/books/{b["id"]}/cover" type="image/jpeg"/>
  {acq_links}
  <link rel="related" href="/api/v1/opds/recommendations/{b["id"]}" type="application/atom+xml;profile=opds-catalog" title="Similar Books"/>
  {f'<dcterms:extent xmlns:dcterms="http://purl.org/dc/terms/">{b["page_count"]} pages</dcterms:extent>' if b.get("page_count") else ""}
  {f'<opds:readingTime xmlns:opds="http://brainycat.app/opds">{b["estimated_reading_minutes"]} min</opds:readingTime>' if b.get("estimated_reading_minutes") else ""}
  {f'<opds:quality xmlns:opds="http://brainycat.app/opds">{b["quality_score"]}/100</opds:quality>' if b.get("quality_score") else ""}
</entry>"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
