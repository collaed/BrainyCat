"""Catalog routes — Gutenberg, LibriVox, Standard Ebooks, GitHub, OAPEN, etc."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query

from brainycat import db
from brainycat.auth import get_current_user, require_admin
from brainycat.http_client import get_client

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/gutenberg/search")
async def gutenberg_search(
    q: str = Query(""), language: str = Query("en"), page: int = Query(1), _u: Any = Depends(get_current_user)
) -> Any:
    from brainycat.sources.gutendex import browse, search

    if q:
        result = await search(title=q, language=language)
        # Cross-link: find matching LibriVox audiobooks
        if result and result.get("books"):
            from brainycat.sources.librivox import search as lv_search

            for book in result["books"][:10]:
                authors = book.get("authors", [])
                author_query = authors[0].split(",")[0].split()[-1] if authors else ""
                if author_query:
                    lv = await lv_search(author=author_query)
                    lv_books = (lv or {}).get("books", [])
                    # Match by title similarity
                    title_lower = (book.get("title") or "").lower()
                    for lb in lv_books:
                        if any(w in (lb.get("title") or "").lower() for w in title_lower.split()[:3] if len(w) > 3):
                            book["audiobook"] = {
                                "librivox_id": lb.get("librivox_id"),
                                "title": lb.get("title"),
                                "totaltime": lb.get("totaltime"),
                                "num_sections": lb.get("num_sections"),
                            }
                            break
        return result
    return await browse(language=language, page=page)


@router.get("/gutenberg/{gutenberg_id}")
async def gutenberg_detail(gutenberg_id: int, _u: Any = Depends(get_current_user)) -> Any:
    from brainycat.sources.gutendex import get_book

    return await get_book(gutenberg_id)


@router.post("/gutenberg/{gutenberg_id}/import")
async def gutenberg_import(gutenberg_id: int, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID, uuid4

    from brainycat.sources.gutendex import get_book as gb
    from brainycat.storage import book_dir

    data = await gb(gutenberg_id)
    if not data or not data.get("epub_url"):
        return {"error": "No EPUB available"}
    client = get_client()
    resp = await client.get(data["epub_url"])
    if resp.status_code != 200:
        return {"error": "Download failed"}
    bid = str(uuid4())
    d = book_dir(bid)
    import os

    path = os.path.join(d, f"{data['title'][:50]}.epub")
    with open(path, "wb") as f:
        f.write(resp.content)
    await db.execute(
        "INSERT INTO books (id, title, description) VALUES ($1,$2,$3)",
        UUID(bid),
        data["title"],
        data.get("description"),
    )
    await db.execute(
        "INSERT INTO book_files (book_id, format, file_path, file_name, file_size) VALUES ($1,'epub',$2,$3,$4)",
        UUID(bid),
        path,
        os.path.basename(path),
        len(resp.content),
    )
    for a in data.get("authors", []):
        await db.execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", a)
        ar = await db.fetch_one("SELECT id FROM authors WHERE name = $1", a)
        if ar:
            await db.execute(
                "INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                UUID(bid),
                ar["id"],
            )
    return {"book_id": bid, "title": data["title"]}


@router.get("/librivox/search")
async def librivox_search(title: str = Query(""), author: str = Query(""), _u: Any = Depends(get_current_user)) -> Any:
    from brainycat.sources.librivox import search

    return await search(title=title or None, author=author or None)


@router.post("/librivox/{librivox_id}/import")
async def librivox_import(librivox_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Download a LibriVox audiobook (all chapters) into the library."""
    from uuid import UUID as _UUID
    from uuid import uuid4 as _uuid4

    import httpx as _httpx

    from brainycat.sources.librivox import get_book as _lb
    from brainycat.sources.librivox import get_chapters as _lc
    from brainycat.storage import book_dir as _bd

    data = await _lb(librivox_id)
    if not data:
        return {"error": "Book not found on LibriVox"}

    bid = str(_uuid4())
    out_dir = _bd(bid)

    # Create book record
    await db.execute(
        "INSERT INTO books (id, title, description) VALUES ($1, $2, $3)",
        _UUID(bid),
        data["title"],
        data.get("description"),
    )
    for a in data.get("authors", []):
        if a:
            await db.execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", a)
            ar = await db.fetch_one("SELECT id FROM authors WHERE name = $1", a)
            if ar:
                await db.execute(
                    "INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", _UUID(bid), ar["id"]
                )

    # Download chapters from RSS
    chapters = await _lc(data["url_rss"]) if data.get("url_rss") else []
    downloaded = 0

    async with _httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for i, ch in enumerate(chapters):
            try:
                resp = await client.get(ch["url"])
                if resp.status_code == 200:
                    fname = f"{i + 1:02d} - {ch['title'][:40]}.mp3"
                    fname = "".join(c for c in fname if c.isalnum() or c in " -_.").strip()
                    fpath = os.path.join(out_dir, fname)
                    with open(fpath, "wb") as f:
                        f.write(resp.content)
                    await db.execute(
                        """INSERT INTO book_files (book_id, format, file_path, file_name, file_size, mime_type)
                           VALUES ($1, 'mp3', $2, $3, $4, 'audio/mpeg')""",
                        _UUID(bid),
                        fpath,
                        fname,
                        len(resp.content),
                    )
                    downloaded += 1
            except Exception:
                continue

    return {"book_id": bid, "title": data["title"], "chapters_downloaded": downloaded, "total_chapters": len(chapters)}


@router.get("/crosslink")
async def catalog_crosslink(title: str = Query(""), author: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Find matching ebook + audiobook across Gutenberg and LibriVox."""
    from brainycat.sources.gutendex import search as gut_search
    from brainycat.sources.librivox import search as lv_search

    ebook = await gut_search(title=title or None) if title else None
    audiobook = await lv_search(title=title or None, author=author or None)

    # Match by normalized author name
    matches = []
    gut_books = (ebook or {}).get("books", [])
    lv_books = (audiobook or {}).get("books", [])

    for gb in gut_books:
        gb_authors = {a.lower().split(",")[0].split()[-1] for a in (gb.get("authors") or [])}
        for lb in lv_books:
            lb_authors = {a.lower().split()[-1] for a in (lb.get("authors") or [])}
            if gb_authors & lb_authors:
                matches.append({"ebook": gb, "audiobook": lb})
                break

    return {
        "matches": matches,
        "ebooks_only": [b for b in gut_books if not any(m["ebook"] == b for m in matches)],
        "audiobooks_only": [b for b in lv_books if not any(m["audiobook"] == b for m in matches)],
    }


@router.post("/sync/gutenberg")
async def sync_gut(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.catalog_cache import sync_gutenberg

    return await sync_gutenberg()


@router.post("/sync/librivox")
async def sync_lv(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.catalog_cache import sync_librivox

    return await sync_librivox()


@router.post("/sync/crosslinks")
async def sync_crosslinks(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.catalog_cache import compute_crosslinks

    return await compute_crosslinks()


@router.get("/cached")
async def cached_search(
    q: str = Query(""), source: str = Query("gutenberg"), language: str = Query("en"), _u: Any = Depends(get_current_user)
) -> dict[str, Any]:
    from brainycat.catalog_cache import search_cached

    return await search_cached(q, source, language)


@router.get("/standard-ebooks/search")
async def standard_ebooks_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> Any:
    from brainycat.sources.standard_ebooks import search

    return await search(q)


@router.get("/github/search")
async def github_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.github_books import search_ebooks

    return await search_ebooks(q)


@router.get("/github/awesome")
async def github_awesome(topic: str = Query("books"), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.github_books import search_awesome_lists

    return await search_awesome_lists(topic)


@router.get("/github/{owner}/{repo}/files")
async def github_files(owner: str, repo: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.github_books import find_epub_files

    return await find_epub_files(owner, repo)


@router.get("/oapen/search")
async def oapen_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_textbooks import search_oapen

    return await search_oapen(q)


@router.get("/openstax")
async def openstax_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_textbooks import search_openstax

    return await search_openstax(q)


@router.get("/open-textbooks/search")
async def otl_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_textbooks import search_open_textbook_library

    return await search_open_textbook_library(q)


@router.get("/search")
async def unified_catalog_search(q: str = Query(""), language: str = Query("en"), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Search all catalog sources in parallel, grouped by type."""
    import asyncio

    from brainycat.catalog_cache import search_cached
    from brainycat.sources.github_books import search_ebooks as gh_search
    from brainycat.sources.gutendex import search as gut_search
    from brainycat.sources.librivox import search as lv_search
    from brainycat.sources.open_textbooks import search_oapen, search_openstax
    from brainycat.sources.standard_ebooks import search as se_search

    if not q:
        return {"ebooks": [], "audiobooks": [], "textbooks": [], "github": []}

    async def safe(coro: Any) -> dict[str, Any]:
        try:
            return await coro
        except Exception:
            return {"books": []}

    # Try cache first for Gutenberg + LibriVox
    cached_gut, cached_lv = await asyncio.gather(
        search_cached(q, "gutenberg", language),
        search_cached(q, "librivox", ""),
    )

    # If cache has results, use those; otherwise fan out to live APIs
    if cached_gut.get("books"):
        gut_result = cached_gut
        lv_result = cached_lv
        # Still fetch textbooks + github in parallel
        se_result, oapen_result, openstax_result, gh_result = await asyncio.gather(
            se_search(q),
            search_oapen(q),
            search_openstax(q),
            gh_search(q, limit=10),
        )
    else:
        # All live, in parallel
        gut_raw, lv_result, se_result, oapen_result, openstax_result, gh_result = await asyncio.gather(
            safe(gut_search(title=q, language=language)),
            safe(lv_search(title=q)),
            safe(se_search(q)),
            safe(search_oapen(q)),
            safe(search_openstax(q)),
            safe(gh_search(q, limit=10)),
        )
        gut_result = gut_raw or {"books": []}

    return {
        "ebooks": (gut_result.get("books") or [])[:15] + (se_result.get("books") or [])[:5],
        "audiobooks": (lv_result.get("books") or [])[:15],
        "textbooks": (oapen_result.get("books") or [])[:10] + (openstax_result.get("books") or [])[:5],
        "github": (gh_result.get("books") or [])[:10],
    }


@router.get("/check-owned")
async def check_owned(title: str = Query(""), isbn: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Check if a catalog book is already in the user's library."""
    if isbn:
        row = await db.fetch_one("SELECT id, title, quality_score FROM books WHERE isbn = $1", isbn)
        if row:
            return {"owned": True, "book_id": str(row["id"]), "title": row["title"], "quality": row["quality_score"]}
    if title:
        row = await db.fetch_one("SELECT id, title, quality_score FROM books WHERE title ILIKE $1", title)
        if row:
            return {"owned": True, "book_id": str(row["id"]), "title": row["title"], "quality": row["quality_score"]}
        # Fuzzy: check if any book has >60% word overlap
        words = {w.lower() for w in title.split() if len(w) > 3}
        if words:
            rows = await db.fetch_all("SELECT id, title FROM books LIMIT 2000")
            for r in rows:
                book_words = {w.lower() for w in (r["title"] or "").split() if len(w) > 3}
                if words and book_words and len(words & book_words) / len(words) > 0.6:
                    return {"owned": True, "book_id": str(r["id"]), "title": r["title"], "match": "fuzzy"}
    # Check by Open Library Work ID (catches different editions)
    if isbn:
        try:
            cl = get_client()
            resp = await cl.get(f"https://openlibrary.org/isbn/{isbn}.json", timeout=5)
            if resp.status_code == 200:
                works = resp.json().get("works", [])
                if works:
                    work_key = works[0].get("key", "").replace("/works/", "")
                    if work_key:
                        owned = await db.fetch_one(
                            "SELECT id, title FROM books WHERE extra_metadata->>'ol_work_id' = $1 LIMIT 1",
                            work_key,
                        )
                        if owned:
                            return {
                                "owned": True,
                                "book_id": str(owned["id"]),
                                "title": owned["title"],
                                "match": "work_id",
                                "work_id": work_key,
                            }
        except Exception:
            pass
    return {"owned": False}


@router.get("/opds-import")
async def opds_import_search(url: str = Query(""), q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Search an external OPDS feed (calibre-server, Kavita, Komga, etc.)."""
    from xml.etree import ElementTree as ET

    if not url:
        return {"error": "provide OPDS feed URL"}
    try:
        client = get_client()
        search_url = f"{url.rstrip('/')}/search?q={q}" if q else url
        resp = await client.get(search_url)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom", "opds": "http://opds-spec.org/2010/catalog"}
        books = []
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns)
            author = entry.findtext("atom:author/atom:name", "", ns)
            books.append({"title": title, "authors": [author] if author else [], "source": "opds_external"})
        return {"books": books, "feed_title": root.findtext("atom:title", "", ns)}
    except Exception as e:
        return {"error": str(e)[:100]}


@router.get("/manybooks/search")
async def manybooks_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Search ManyBooks (50K+ free ebooks)."""

    try:
        c = get_client()
        r = await c.get(f"https://manybooks.net/search-book?search={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            import re

            books = []
            for m in re.finditer(r'<a href="(/titles/[^"]+)"[^>]*>([^<]+)</a>', r.text):
                books.append({"source": "manybooks", "title": m.group(2).strip(), "url": f"https://manybooks.net{m.group(1)}"})
                if len(books) >= 20:
                    break
            return {"books": books}
    except Exception:
        pass
    return {"books": []}


@router.get("/free-computer-books/search")
async def free_computer_books(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Search Free Computer Books (technical/programming)."""

    try:
        c = get_client()
        r = await c.get(f"https://freecomputerbooks.com/search.html?cx=partner-pub-7&q={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            import re

            books = []
            for m in re.finditer(r'<a href="(https?://freecomputerbooks\.com/[^"]+\.html)"[^>]*>([^<]+)</a>', r.text):
                title = m.group(2).strip()
                if len(title) > 5 and "search" not in title.lower():
                    books.append({"source": "free_computer_books", "title": title, "url": m.group(1)})
                    if len(books) >= 20:
                        break
            return {"books": books}
    except Exception:
        pass
    return {"books": []}


# ── Additional free catalog sources ───────────────────────────────────────


@router.get("/feedbooks/search")
async def search_feedbooks(q: str = Query(...), limit: int = Query(20)) -> dict[str, Any]:
    """Search Feedbooks public domain catalog (OPDS)."""
    client = get_client()
    resp = await client.get(
        f"https://catalog.feedbooks.com/publicdomain/browse/search.atom?query={q}",
        timeout=10,
    )
    if resp.status_code != 200:
        return {"results": [], "error": f"HTTP {resp.status_code}"}
    import re

    entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
    results = []
    for entry in entries[:limit]:
        title = re.search(r"<title>([^<]+)</title>", entry)
        author = re.search(r"<name>([^<]+)</name>", entry)
        epub_link = re.search(r'href="([^"]+\.epub)"', entry)
        cover = re.search(r'href="([^"]+)"[^>]*type="image', entry)
        results.append(
            {
                "title": title.group(1) if title else "",
                "author": author.group(1) if author else "",
                "epub_url": epub_link.group(1) if epub_link else None,
                "cover_url": cover.group(1) if cover else None,
                "source": "feedbooks",
            }
        )
    return {"results": results}


@router.get("/archive/search")
async def search_internet_archive(q: str = Query(...), limit: int = Query(20)) -> dict[str, Any]:
    """Search Internet Archive for free ebooks."""
    client = get_client()
    resp = await client.get(
        "https://archive.org/advancedsearch.php",
        params={
            "q": f"{q} AND mediatype:texts AND format:epub",
            "fl[]": "identifier,title,creator,description,year",
            "rows": limit,
            "output": "json",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return {"results": []}
    data = resp.json()
    results = []
    for doc in data.get("response", {}).get("docs", []):
        ident = doc.get("identifier", "")
        results.append(
            {
                "title": doc.get("title", ""),
                "author": doc.get("creator", ""),
                "description": (doc.get("description", "") or "")[:300],
                "year": doc.get("year"),
                "epub_url": f"https://archive.org/download/{ident}/{ident}.epub",
                "cover_url": f"https://archive.org/services/img/{ident}",
                "source": "internet_archive",
                "id": ident,
            }
        )
    return {"results": results}


@router.get("/doab/search")
async def search_doab(q: str = Query(...), limit: int = Query(20)) -> dict[str, Any]:
    """Search Directory of Open Access Books."""
    client = get_client()
    resp = await client.get(
        f"https://directory.doabooks.org/rest/search?query={q}&expand=metadata",
        timeout=10,
    )
    if resp.status_code != 200:
        return {"results": []}
    items = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", [])
    results = []
    for item in items[:limit]:
        meta = {}
        for m in item.get("metadata", []):
            meta[m.get("key", "")] = m.get("value", "")
        results.append(
            {
                "title": meta.get("dc.title", ""),
                "author": meta.get("dc.contributor.author", ""),
                "isbn": meta.get("dc.identifier.isbn", ""),
                "description": meta.get("dc.description.abstract", "")[:300],
                "source": "doab",
            }
        )
    return {"results": results}


@router.get("/loyalbooks/search")
async def search_loyalbooks(q: str = Query(...), limit: int = Query(20)) -> dict[str, Any]:
    """Search Loyal Books free audiobooks."""
    client = get_client()
    resp = await client.get(f"http://www.loyalbooks.com/search?q={q}", timeout=10)
    if resp.status_code != 200:
        return {"results": []}
    import re

    titles = re.findall(r'<a href="/book/([^"]+)"[^>]*>([^<]+)</a>', resp.text)
    results = []
    for slug, title in titles[:limit]:
        results.append(
            {
                "title": title.strip(),
                "url": f"http://www.loyalbooks.com/book/{slug}",
                "source": "loyalbooks",
            }
        )
    return {"results": results}


# ── Available catalog sources ─────────────────────────────────────────────
@router.get("/sources")
async def catalog_sources() -> list[dict[str, Any]]:
    """List all available free catalog sources."""
    return [
        {"id": "gutenberg", "name": "Project Gutenberg", "count": "70,000+", "type": "ebooks", "api": True},
        {"id": "standard-ebooks", "name": "Standard Ebooks", "count": "700+", "type": "ebooks", "api": True},
        {"id": "librivox", "name": "LibriVox", "count": "18,000+", "type": "audiobooks", "api": True},
        {"id": "feedbooks", "name": "Feedbooks Public Domain", "count": "5,000+", "type": "ebooks", "api": True},
        {"id": "archive", "name": "Internet Archive", "count": "28M+", "type": "ebooks", "api": True},
        {"id": "oapen", "name": "OAPEN", "count": "20,000+", "type": "academic", "api": True},
        {"id": "openstax", "name": "OpenStax", "count": "50+", "type": "textbooks", "api": True},
        {"id": "doab", "name": "DOAB", "count": "60,000+", "type": "academic", "api": True},
        {"id": "loyalbooks", "name": "Loyal Books", "count": "7,000+", "type": "audiobooks", "api": True},
        {"id": "manybooks", "name": "ManyBooks", "count": "50,000+", "type": "ebooks", "api": True},
        {"id": "github", "name": "GitHub Ebooks", "count": "varies", "type": "tech", "api": True},
    ]
