"""Routes: admin."""

from __future__ import annotations

import os
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, UploadFile

from brainycat import db, stats
from brainycat.auth import get_current_user, require_admin
from brainycat.config import settings
from brainycat.http_client import get_client

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    j = await db.fetch_one("SELECT * FROM async_jobs WHERE id::text = $1 OR remote_job_id = $1", job_id)
    return dict(j) if j else {"error": "not found"}


# ── Kindle / device delivery ─────────────────────────────────────────────


@router.get("/stats/overview")
async def stats_overview(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await stats.get_stats(str(user["id"]))


@router.get("/notes/export")
async def export_notes(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await stats.export_notes(str(user["id"]))


# ── OPDS ─────────────────────────────────────────────────────────────────


@router.post("/import/goodreads")
async def import_gr(file: UploadFile, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.importers.calibre import import_goodreads

    content = (await file.read()).decode()
    return await import_goodreads(content)


@router.post("/import/audiobookshelf")
async def import_abs(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.importers.calibre import import_audiobookshelf

    return await import_audiobookshelf()


# ── RSS feed ─────────────────────────────────────────────────────────────


@router.post("/covers/optimize")
async def optimize_covers(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.covers import optimize_all_covers

    return await optimize_all_covers()


@router.post("/covers/generate-missing")
async def gen_covers(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.covers import generate_missing_covers

    return await generate_missing_covers()


# ── OCR ──────────────────────────────────────────────────────────────────


@router.post("/covers/extract-pdf")
async def extract_pdf_covers(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Extract covers from PDFs that don't have one."""
    from brainycat.ocr import extract_pdf_cover
    from brainycat.storage import book_dir as _bdir

    rows = await db.fetch_all("""
        SELECT b.id, bf.file_path FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        WHERE bf.format = 'pdf' AND (b.cover_path IS NULL OR b.cover_path = '')
    """)
    extracted = 0
    for r in rows:
        if not os.path.isfile(r["file_path"]):
            continue
        cover_path = os.path.join(_bdir(str(r["id"])), "cover.jpg")
        if extract_pdf_cover(r["file_path"], cover_path):
            await db.execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, r["id"])
            extracted += 1
    return {"extracted": extracted}


# ── Fingerprints & Content Duplicates ────────────────────────────────────


@router.get("/ui/skins")
async def list_skins() -> list[dict[str, str]]:
    return [
        {"id": "default", "name": "BrainyCat Classic", "description": "Grid/list library view"},
        {"id": "spreadsheet", "name": "Spreadsheet", "description": "Data-first: dense grid, inline edit, batch actions"},
        {"id": "cockpit", "name": "Cockpit", "description": "Dashboard: sidebar nav, stats widgets, quick actions"},
        {"id": "notebook", "name": "Notebook", "description": "Clean & minimal: white space, hidden menus, slash commands"},
        {"id": "canvas", "name": "Canvas", "description": "Drag-and-drop: floating panels, spatial organization"},
        {"id": "wizard", "name": "Wizard", "description": "Guided: step-by-step flows for complex tasks"},
    ]


# ── Book Genome / Taste Engine ───────────────────────────────────────────


@router.post("/import/calibre")
async def import_calibre(path: str = Query(...), _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.calibre_import import calibre_library_stats, detect_calibre_library

    if not detect_calibre_library(path):
        return {"error": "Not a Calibre library (no metadata.db)"}
    return {"detected": True, "stats": calibre_library_stats(path)}


@router.post("/import/calibre/run")
async def run_calibre_import(path: str = Query(...), _a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Import books from Calibre library into BrainyCat."""
    from brainycat.calibre_import import detect_calibre_library, read_calibre_db

    if not detect_calibre_library(path):
        return {"error": "Not a Calibre library"}

    books = read_calibre_db(path)
    imported = 0
    skipped = 0
    annotations_imported = 0
    for b in books:
        # Skip if already exists (by UUID, ISBN, or title)
        if b.get("uuid"):
            existing = await db.fetch_one("SELECT id FROM books WHERE calibre_uuid = $1", b["uuid"])
            if existing:
                skipped += 1
                continue
        if b.get("isbn"):
            existing = await db.fetch_one("SELECT id FROM books WHERE isbn = $1", b["isbn"])
            if existing:
                skipped += 1
                continue
        existing = await db.fetch_one("SELECT id FROM books WHERE title = $1", b["title"])
        if existing:
            skipped += 1
            continue

        import shutil
        import uuid

        book_id = uuid.uuid4()
        await db.execute(
            "INSERT INTO books (id, title, isbn, description, rating) VALUES ($1,$2,$3,$4,$5)",
            book_id,
            b["title"],
            b.get("isbn"),
            b.get("description"),
            (b.get("rating") or 0) / 2,
        )
        # Authors (with sort names)
        for author in b.get("authors", []):
            name = author["name"] if isinstance(author, dict) else author
            author_row = await db.fetch_one("SELECT id FROM authors WHERE name = $1", name)
            if not author_row:
                aid = uuid.uuid4()
                await db.execute("INSERT INTO authors (id, name) VALUES ($1,$2)", aid, name)
            else:
                aid = author_row["id"]
            await db.execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", book_id, aid)
        # Tags
        for tag_name in b.get("tags", []):
            await db.execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", tag_name)
            tag_row = await db.fetch_one("SELECT id FROM tags WHERE name = $1", tag_name)
            if tag_row:
                await db.execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", book_id, tag_row["id"])
        # Series with correct index
        if b.get("series_name"):
            await db.execute("INSERT INTO series (name) VALUES ($1) ON CONFLICT DO NOTHING", b["series_name"])
            series_row = await db.fetch_one("SELECT id FROM series WHERE name = $1", b["series_name"])
            if series_row:
                await db.execute(
                    "INSERT INTO books_series (book_id, series_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    book_id,
                    series_row["id"],
                )
                await db.execute("UPDATE books SET series_index = $1 WHERE id = $2", b.get("series_index", 1), book_id)
        # Identifiers (ASIN, DOI, Google Books, etc.)
        for id_type, id_val in b.get("identifiers", {}).items():
            if id_type == "isbn" and not b.get("isbn"):
                await db.execute("UPDATE books SET isbn = $1 WHERE id = $2", id_val, book_id)
            # Store all identifiers in extra_metadata
        if b.get("identifiers"):
            import json

            await db.execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
                json.dumps({"calibre_identifiers": b["identifiers"]}),
                book_id,
            )
        # Files
        for f in b.get("files", []):
            dest = f"/data/books/{book_id}.{f['format']}"
            try:
                shutil.copy2(f["path"], dest)
                await db.execute(
                    "INSERT INTO book_files (id, book_id, format, file_path) VALUES ($1,$2,$3,$4)",
                    uuid.uuid4(),
                    book_id,
                    f["format"],
                    dest,
                )
            except Exception:
                pass
        # Cover
        if b.get("cover_path"):
            dest = f"/data/covers/{book_id}.jpg"
            try:
                shutil.copy2(b["cover_path"], dest)
                await db.execute("UPDATE books SET cover_path = $1 WHERE id = $2", dest, book_id)
            except Exception:
                pass
        # Annotations from Calibre
        for ann in b.get("annotations", []):
            try:
                await db.execute(
                    "INSERT INTO annotations (id, book_id, content, annotation_type) VALUES ($1,$2,$3,$4)",
                    uuid.uuid4(),
                    book_id,
                    str(ann.get("data", "")),
                    ann.get("type", "highlight"),
                )
                annotations_imported += 1
            except Exception:
                pass
        imported += 1

    return {"imported": imported, "skipped": skipped, "annotations": annotations_imported, "total_in_calibre": len(books)}


# ── EPUB Lint ────────────────────────────────────────────────────────────


@router.post("/import/goodreads")
async def import_goodreads(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import Goodreads CSV export. Send CSV as request body."""
    from brainycat.goodreads import import_goodreads_csv

    body = await request.body()
    csv_content = body.decode("utf-8", errors="replace")
    return await import_goodreads_csv(csv_content, str(user["id"]))


# ── Device annotation import ─────────────────────────────────────────────


@router.post("/import/kindle-clippings")
async def import_kindle(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import Kindle My Clippings.txt. Send file content as request body."""
    from brainycat.device_import import import_kindle_clippings

    body = await request.body()
    return await import_kindle_clippings(body.decode("utf-8", errors="replace"), str(user["id"]))


@router.post("/import/kobo")
async def import_kobo(path: str = Query(...), user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import annotations from Kobo KoboReader.sqlite."""
    from brainycat.device_import import import_kobo_annotations

    return await import_kobo_annotations(path, str(user["id"]))


# ── WordDumb (Word Wise + X-Ray) ─────────────────────────────────────────


@router.get("/jobs")
async def list_async_jobs(book_id: str = Query(None), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.async_jobs import list_jobs

    return await list_jobs(book_id)


# ── Plugin system ────────────────────────────────────────────────────────


@router.get("/plugins")
async def list_plugins(_a: Any = Depends(require_admin)) -> list[dict[str, str]]:
    from brainycat.plugins import get_plugins

    return get_plugins()


# ── Custom columns ───────────────────────────────────────────────────────


@router.get("/custom-columns")
async def get_custom_columns(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.custom_columns import list_columns

    return await list_columns()


@router.post("/custom-columns")
async def create_custom_column(request: Request, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.custom_columns import create_column

    body = await request.json()
    return await create_column(body["name"], body["label"], body.get("datatype", "text"))


@router.get("/virtual-libraries")
async def get_vlibs(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.virtual_libraries import list_virtual_libraries

    return await list_virtual_libraries(str(user["id"]))


@router.post("/virtual-libraries")
async def create_vlib(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.virtual_libraries import create_virtual_library

    body = await request.json()
    return await create_virtual_library(str(user["id"]), body["name"], body["query"], body.get("filters"))


@router.delete("/virtual-libraries/{vlib_id}")
async def delete_vlib(vlib_id: str, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from brainycat.virtual_libraries import delete_virtual_library

    return await delete_virtual_library(vlib_id, str(user["id"]))


# ── Federated social ─────────────────────────────────────────────────────


@router.post("/diff")
async def edition_diff(request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.edition_diff import diff_editions

    body = await request.json()
    return await diff_editions(body["book_a"], body["book_b"])


# ── Gutenberg ↔ LibriVox cross-linking ────────────────────────────────────


# ── Catalog cache ─────────────────────────────────────────────────────────


# ── User language preferences ─────────────────────────────────────────────


@router.get("/calibre/pending")
async def calibre_pending(library_path: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get pending enrichments to push back to Calibre."""
    rows = await db.fetch_all("""
        SELECT b.id, b.title, b.isbn, b.description, b.rating,
               b.extra_metadata,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM books b
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE b.extra_metadata ? 'enriched_fields'
        GROUP BY b.id LIMIT 100
    """)
    return {
        "pending": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "isbn": r["isbn"],
                "description": (r["description"] or "")[:2000],
                "rating": r["rating"],
                "tags": r["tags"] or [],
            }
            for r in rows
        ]
    }


@router.post("/calibre/push")
async def calibre_push(request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Receive books pushed from Calibre plugin."""
    body = await request.json()
    books = body.get("books", [])
    received = 0
    for b in books:
        import uuid as _uuid

        existing = await db.fetch_one("SELECT id FROM books WHERE title = $1", b.get("title", ""))
        if existing:
            # Update with Calibre data
            if b.get("isbn"):
                await db.execute("UPDATE books SET isbn = $1 WHERE id = $2 AND isbn IS NULL", b["isbn"], existing["id"])
            received += 1
        else:
            # Create new book from Calibre push
            bid = _uuid.uuid4()
            await db.execute(
                "INSERT INTO books (id, title, isbn, description) VALUES ($1,$2,$3,$4)",
                bid,
                b.get("title"),
                b.get("isbn"),
                b.get("description"),
            )
            received += 1
    return {"received": received}


@router.post("/calibre/ack")
async def calibre_ack(request: Request, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    """Acknowledge that enrichments were applied in Calibre."""
    body = await request.json()
    # Mark enrichments as synced
    for bid in body.get("ids", []):
        from uuid import UUID as _UUID

        with suppress(Exception):
            await db.execute(
                "UPDATE books SET extra_metadata = extra_metadata - 'enriched_fields' WHERE id = $1",
                _UUID(bid),
            )
    return {"ok": True}


# ── "You already own this" detection ──────────────────────────────────────


# ── Library health report ─────────────────────────────────────────────────


@router.post("/notify")
async def send_notification(request: Request, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Send notification via Signal or Gotify."""

    body = await request.json()
    msg = body.get("message", "")
    results = {}

    # Signal (existing)
    if settings.signal_api_url:
        try:
            c = get_client()
            r = await c.post(f"{settings.signal_api_url}/v2/send", json={"message": msg, "number": body.get("number", "")})
            results["signal"] = r.status_code == 200
        except Exception:
            results["signal"] = False

    # Gotify
    gotify_url = getattr(settings, "gotify_url", "") or ""
    gotify_token = getattr(settings, "gotify_token", "") or ""
    if gotify_url and gotify_token:
        try:
            c = get_client()
            r = await c.post(f"{gotify_url}/message?token={gotify_token}", json={"title": "BrainyCat", "message": msg, "priority": 5})
            results["gotify"] = r.status_code == 200
        except Exception:
            results["gotify"] = False

    return results


# ── Review aggregation (7 sources) ────────────────────────────────────────


@router.post("/import/zotero")
async def import_zotero(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import books from Zotero library via API key."""
    body = await request.json()
    api_key = body.get("api_key", "")
    user_id = body.get("zotero_user_id", "")
    if not api_key or not user_id:
        return {"error": "provide api_key and zotero_user_id"}

    c = get_client()
    imported = 0
    try:
        resp = await c.get(
            f"https://api.zotero.org/users/{user_id}/items?format=json&itemType=book&limit=50",
            headers={"Zotero-API-Key": api_key},
        )
        if resp.status_code != 200:
            return {"error": f"Zotero API: {resp.status_code}"}
        for item in resp.json():
            data = item.get("data", {})
            title = data.get("title", "")
            if not title:
                continue
            existing = await db.fetch_one("SELECT id FROM books WHERE title = $1", title)
            if existing:
                continue
            import uuid

            bid = uuid.uuid4()
            isbn = data.get("ISBN", "")
            authors = [
                f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
                for c in data.get("creators", [])
                if c.get("creatorType") == "author"
            ]
            await db.execute(
                "INSERT INTO books (id, title, isbn, description) VALUES ($1,$2,$3,$4)", bid, title, isbn or None, data.get("abstractNote")
            )
            for author in authors:
                if author:
                    await db.execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", author)
                    arow = await db.fetch_one("SELECT id FROM authors WHERE name=$1", author)
                    if arow:
                        await db.execute(
                            "INSERT INTO books_authors (book_id, author_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", bid, arow["id"]
                        )
            imported += 1
    except Exception as e:
        return {"error": str(e)[:100]}
    return {"imported": imported}


# ── Series Management ─────────────────────────────────────────────────────


@router.get("/stats/dashboard")
async def stats_dashboard(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Full intelligence + enrichment + conversion statistics."""
    # Library overview
    overview = await db.fetch_one("""
        SELECT
            count(*) as total_books,
            count(*) FILTER (WHERE isbn IS NOT NULL) as has_isbn,
            count(*) FILTER (WHERE description IS NOT NULL AND description != '') as has_description,
            count(*) FILTER (WHERE cover_path IS NOT NULL) as has_cover,
            count(*) FILTER (WHERE embedding IS NOT NULL) as has_embedding,
            count(*) FILTER (WHERE quality_score > 50) as good_quality,
            count(*) FILTER (WHERE word_count IS NOT NULL) as has_wordcount,
            count(*) FILTER (WHERE rating IS NOT NULL AND rating > 0) as has_rating,
            count(*) FILTER (WHERE language IS NOT NULL AND language != '') as has_language,
            count(*) FILTER (WHERE EXISTS (SELECT 1 FROM books_tags bt WHERE bt.book_id = b.id)) as has_tags,
            avg(quality_score) FILTER (WHERE quality_score > 0) as avg_quality
        FROM books b
    """)

    # Enrichment per source
    enrichment = await db.fetch_all("""
        SELECT method,
            count(*) as attempts,
            count(*) FILTER (WHERE success) as successes,
            round(100.0 * count(*) FILTER (WHERE success) / NULLIF(count(*), 0), 1) as hit_rate_pct,
            max(created_at) as last_attempt
        FROM enrichment_log GROUP BY method ORDER BY attempts DESC
    """)

    # Format distribution
    formats = await db.fetch_all("""
        SELECT format, count(*) as cnt, sum(file_size) as total_size
        FROM book_files GROUP BY format ORDER BY cnt DESC
    """)

    # Tags
    tag_stats = await db.fetch_one("""
        SELECT count(DISTINCT bt.book_id) as tagged_books,
               count(DISTINCT t.id) as unique_tags
        FROM books_tags bt JOIN tags t ON t.id = bt.tag_id
    """)
    top_tags = await db.fetch_all("""
        SELECT t.name, count(*) as cnt FROM books_tags bt
        JOIN tags t ON t.id = bt.tag_id GROUP BY t.name ORDER BY cnt DESC LIMIT 15
    """)

    # Authors
    author_stats = await db.fetch_one("SELECT count(*) as total FROM authors")
    dup_authors = await db.fetch_one("""
        SELECT count(*) FROM (
            SELECT lower(regexp_replace(name, '[^a-zA-Z ]', '', 'g')) as norm
            FROM authors GROUP BY norm HAVING count(*) > 1
        ) x
    """)

    # Series
    series_stats = await db.fetch_all("""
        SELECT s.name, count(bs.book_id) as books FROM series s
        LEFT JOIN books_series bs ON bs.series_id = s.id
        GROUP BY s.id ORDER BY books DESC LIMIT 10
    """)

    # Background processes
    n = overview or {}
    total = n.get("total_books", 0) or 0

    return {
        "library": {
            "total_books": total,
            "has_isbn": {"count": n.get("has_isbn", 0), "pct": round((n.get("has_isbn", 0) or 0) / max(total, 1) * 100, 1)},
            "has_description": {
                "count": n.get("has_description", 0),
                "pct": round((n.get("has_description", 0) or 0) / max(total, 1) * 100, 1),
            },
            "has_cover": {"count": n.get("has_cover", 0), "pct": round((n.get("has_cover", 0) or 0) / max(total, 1) * 100, 1)},
            "has_embedding": {"count": n.get("has_embedding", 0), "pct": round((n.get("has_embedding", 0) or 0) / max(total, 1) * 100, 1)},
            "has_tags": {"count": n.get("has_tags", 0), "pct": round((n.get("has_tags", 0) or 0) / max(total, 1) * 100, 1)},
            "has_wordcount": {"count": n.get("has_wordcount", 0), "pct": round((n.get("has_wordcount", 0) or 0) / max(total, 1) * 100, 1)},
            "avg_quality": round(float(n.get("avg_quality", 0) or 0), 1),
        },
        "enrichment": [
            {
                "source": r["method"],
                "attempts": r["attempts"],
                "successes": r["successes"],
                "hit_rate": float(r["hit_rate_pct"] or 0),
                "last_attempt": str(r["last_attempt"] or ""),
            }
            for r in enrichment
        ],
        "formats": [
            {"format": r["format"], "count": r["cnt"], "total_size_mb": round((r["total_size"] or 0) / 1048576, 1)} for r in formats
        ],
        "tags": {
            "tagged_books": tag_stats["tagged_books"] if tag_stats else 0,
            "unique_tags": tag_stats["unique_tags"] if tag_stats else 0,
            "top": [{"name": t["name"], "count": t["cnt"]} for t in top_tags],
        },
        "authors": {"total": author_stats["total"] if author_stats else 0, "duplicate_groups": dup_authors["count"] if dup_authors else 0},
        "series": [{"name": s["name"], "books": s["books"]} for s in series_stats],
    }


# ── Rate limiter status ───────────────────────────────────────────────────


@router.get("/stats/rate-limits")
async def rate_limit_status(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.rate_limit import rate_limiter

    return rate_limiter.get_status()


# ── OCR + EPUB conversion pipeline ───────────────────────────────────────


@router.get("/stats/scraper-diagnostics")
async def scraper_diagnostics(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """For each failing source, show the last query URL so a human can test it."""
    from brainycat.rate_limit import rate_limiter

    status = rate_limiter.get_status()
    diagnostics = []

    for source, info in status.items():
        if info["consecutive_failures"] < 3:
            continue

        # Get the last failed book for this source
        row = await db.fetch_one(
            """
            SELECT el.book_id, b.title, b.isbn
            FROM enrichment_log el JOIN books b ON b.id = el.book_id
            WHERE el.method = $1 AND NOT el.success
            ORDER BY el.created_at DESC LIMIT 1
        """,
            source,
        )

        if not row:
            continue

        # Build the URL a human would visit
        title = row["title"] or ""
        isbn = row["isbn"] or ""
        test_urls = {
            "google": f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
            if isbn
            else f"https://www.googleapis.com/books/v1/volumes?q={title}",
            "amazon": f"https://www.amazon.com/s?k={isbn or title}",
            "openlibrary": f"https://openlibrary.org/search.json?isbn={isbn}"
            if isbn
            else f"https://openlibrary.org/search.json?title={title}",
            "loc": f"https://www.loc.gov/books/?q={isbn or title}&fo=json",
            "gutendex": f"https://gutendex.com/books?search={title}",
        }

        diagnostics.append(
            {
                "source": source,
                "failures": info["consecutive_failures"],
                "backoff_sec": info["backoff_remaining_sec"],
                "last_query": {"book": title, "isbn": isbn, "book_id": str(row["book_id"])},
                "test_url": test_urls.get(source, f"https://www.google.com/search?q={title}+{isbn}"),
                "help": "Click the URL. If it works, we're IP-blocked. Paste any data below to help.",
            }
        )

    return diagnostics


@router.post("/stats/scraper-diagnostics/submit")
async def submit_diagnostic(request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Human submits data they found manually — bypasses the blocked scraper."""
    body = await request.json()
    book_id = body.get("book_id")
    source = body.get("source", "")
    data = body.get("data", {})

    if not book_id or not data:
        return {"error": "provide book_id and data"}

    import json
    from uuid import UUID as _UUID

    from brainycat.rate_limit import rate_limiter

    # Apply whatever data the human provided
    updates = []
    if data.get("title"):
        await db.execute("UPDATE books SET title = $1 WHERE id = $2", data["title"], _UUID(book_id))
        updates.append("title")
    if data.get("isbn"):
        await db.execute("UPDATE books SET isbn = $1 WHERE id = $2", data["isbn"], _UUID(book_id))
        updates.append("isbn")
    if data.get("description"):
        await db.execute("UPDATE books SET description = $1 WHERE id = $2", data["description"][:2000], _UUID(book_id))
        updates.append("description")
    if data.get("authors"):
        updates.append("authors")
    if data.get("cover_url"):
        updates.append("cover_url")

    # Log as successful enrichment
    await db.execute(
        "INSERT INTO enrichment_log (book_id, method, success, details) VALUES ($1, $2, true, $3::jsonb)",
        _UUID(book_id),
        f"human_{source}",
        json.dumps({"fields": updates}),
    )

    # If the human could access the URL, the source is working — we're just blocked
    if body.get("source_accessible"):
        # Jump to max cooldown — we're definitely IP-blocked
        rate_limiter._consecutive_failures[source] = 50
        rate_limiter.report_failure(source)
        return {"ok": True, "updates": updates, "note": f"{source} confirmed IP-blocked, cooldown set to 6 hours"}
    # Source might be down — moderate cooldown
    rate_limiter._consecutive_failures[source] = 20
    rate_limiter.report_failure(source)
    return {"ok": True, "updates": updates, "note": f"{source} may be down, cooldown set to 1 hour"}


# ── ISBN region detection ─────────────────────────────────────────────────


@router.get("/stats/isbn-regions")
async def isbn_region_stats(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Distribution of books by ISBN region — helps prioritize enrichment sources."""
    from brainycat.isbn import isbn_to_region

    rows = await db.fetch_all("SELECT isbn FROM books WHERE isbn IS NOT NULL AND length(isbn) >= 10")
    regions: dict[str, int] = {}
    for r in rows:
        info = isbn_to_region(r["isbn"])
        name = info["region"] if info else "Unknown"
        regions[name] = regions.get(name, 0) + 1
    sorted_regions = sorted(regions.items(), key=lambda x: x[1], reverse=True)
    return {
        "total": len(rows),
        "regions": [{"region": k, "count": v, "pct": round(v / max(len(rows), 1) * 100, 1)} for k, v in sorted_regions],
    }


# ── Open Library Work ID resolution ───────────────────────────────────────


# ── Backup ────────────────────────────────────────────────────────────────
@router.post("/backup")
async def create_backup(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Create a PostgreSQL backup via asyncpg COPY."""
    import gzip
    import time

    ts = time.strftime("%Y%m%d_%H%M%S")
    dump_path = f"/data/backups/brainycat_{ts}.sql.gz"
    os.makedirs("/data/backups", exist_ok=True)

    from brainycat.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        tables = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        with gzip.open(dump_path, "wb") as f:
            for t in tables:
                tname = t["tablename"]
                f.write(f"-- TABLE: {tname}\n".encode())
                import io as _io

                buf = _io.BytesIO()
                await conn.copy_from_table(tname, output=buf, format="csv", header=True)
                data = buf.getvalue()
                if data:
                    f.write(data)
                f.write(b"\n")

    size = os.path.getsize(dump_path)
    total = await db.fetch_one("SELECT count(*) as c FROM books")
    return {"ok": True, "path": dump_path, "size_mb": round(size / 1048576, 1), "books": total["c"], "timestamp": ts}


@router.get("/backups")
async def list_backups(_a: Any = Depends(require_admin)) -> list[dict[str, Any]]:
    """List available backups."""
    backup_dir = "/data/backups"
    if not os.path.isdir(backup_dir):
        return []
    backups = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        if f.endswith(".sql.gz"):
            path = os.path.join(backup_dir, f)
            backups.append(
                {
                    "filename": f,
                    "size_mb": round(os.path.getsize(path) / 1048576, 1),
                    "created": f.replace("brainycat_", "").replace(".sql.gz", ""),
                }
            )
    return backups


# ── Disk usage & cleanup ──────────────────────────────────────────────────
@router.get("/disk-usage")
async def disk_usage(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Report disk usage by category."""
    import subprocess

    result = subprocess.run(["du", "-sh", "/data/books", "/data/backups", "/data/incoming"], capture_output=True, text=True, timeout=30)
    lines = result.stdout.strip().split("\n")
    usage = {}
    for line in lines:
        parts = line.split("\t")
        if len(parts) == 2:
            usage[parts[1].split("/")[-1]] = parts[0]

    # Count orphan OCR results (bloated)
    ocr_size = await db.fetch_one(
        "SELECT count(*) as cnt, COALESCE(sum(file_size),0)/1048576 as mb FROM book_files WHERE file_name = 'ocr_result.pdf'"
    )

    df = subprocess.run(["df", "-h", "/data"], capture_output=True, text=True, timeout=5)

    return {
        "directories": usage,
        "ocr_results": {"count": ocr_size["cnt"], "size_mb": round(float(ocr_size["mb"]))},
        "disk": df.stdout.strip().split("\n")[-1] if df.stdout else "unknown",
    }


# ── Experimental feature evaluation ──────────────────────────────────────
@router.get("/experimental/status")
async def experimental_status() -> dict[str, Any]:
    """Show which experimental features are enabled."""
    from brainycat.config import settings

    return {
        "text_profile": settings.exp_text_profile == "1",
        "lsh_dedup": settings.exp_lsh_dedup == "1",
        "isbntools": settings.exp_isbntools == "1",
        "file_rename": settings.exp_file_rename == "1",
        "kindle_fix": settings.exp_kindle_fix == "1",
    }


@router.post("/experimental/evaluate/{feature}")
async def evaluate_experimental(feature: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    """Run an experimental feature on a sample and compare with existing."""
    book_id = body.get("book_id")

    if feature == "text_profile":
        from brainycat.experimental.text_profile_sig import text_profile_signature

        text = body.get("text", "")
        if not text and book_id:
            # Extract text from book
            from brainycat.db import fetch_one

            row = await fetch_one("SELECT bf.file_path FROM book_files bf WHERE bf.book_id = $1 LIMIT 1", UUID(book_id))
            if row and row["file_path"]:
                import fitz

                try:
                    doc = fitz.open(row["file_path"])
                    text = " ".join(doc[i].get_text() for i in range(min(10, len(doc))))
                    doc.close()
                except Exception:
                    pass
        sig = text_profile_signature(text)
        return {"signature": sig, "text_length": len(text)}

    if feature == "lsh_dedup":
        from brainycat.experimental.lsh_dedup import query_similar, text_to_minhash

        text = body.get("text", "")
        m = text_to_minhash(text)
        return {"num_values": m.count(), "similar": query_similar(text)}

    if feature == "isbntools":
        from brainycat.experimental.isbntools_eval import compare_with_existing, lookup_isbn

        isbn = body.get("isbn", "")
        if book_id and isbn:
            return await compare_with_existing(book_id, isbn)
        if isbn:
            return await lookup_isbn(isbn)
        return {"error": "provide isbn"}

    if feature == "kindle_fix":
        from brainycat.experimental.kindle_epub_fix import fix_epub_for_kindle

        if not book_id:
            return {"error": "provide book_id"}
        from brainycat.db import fetch_one

        row = await fetch_one(
            "SELECT bf.file_path FROM book_files bf WHERE bf.book_id = $1 AND bf.format = 'epub' LIMIT 1",
            UUID(book_id),
        )
        if not row:
            return {"error": "no epub found"}
        # Dry run: copy file, fix, report
        import shutil
        import tempfile

        tmp = tempfile.mktemp(suffix=".epub")
        shutil.copy2(row["file_path"], tmp)
        result = fix_epub_for_kindle(tmp)
        os.unlink(tmp)
        return result

    if feature == "file_rename":
        from brainycat.db import fetch_one
        from brainycat.experimental.file_rename import safe_filename

        if not book_id:
            return {"error": "provide book_id"}
        book = await fetch_one("SELECT b.title, b.author, b.isbn FROM books b WHERE b.id = $1", UUID(book_id))
        if not book:
            return {"error": "not found"}
        title = safe_filename(book["title"] or "Unknown")
        author = safe_filename(book["author"] or "Unknown")
        isbn = book["isbn"] or ""
        proposed = f"{author} - {title}" + (f" [{isbn}]" if isbn else "") + ".epub"
        return {"proposed_filename": proposed, "dry_run": True}

    if feature == "dupe_pages":
        from brainycat.experimental.dupe_pages import detect_duplicate_pages

        if not book_id:
            return {"error": "provide book_id"}
        return await detect_duplicate_pages(book_id)

    return {"error": f"unknown feature: {feature}"}


# ── Experimental: Reading Heatmap ─────────────────────────────────────────
@router.get("/experimental/heatmap")
async def reading_heatmap(days: int = Query(365), user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Reading activity heatmap (GitHub-style contribution graph)."""
    from brainycat.experimental.reading_heatmap import get_heatmap

    data = await get_heatmap(user["id"], days)
    return {"days": data, "total_sessions": sum(d["sessions"] for d in data)}


# ── Experimental: AI Mind Map ─────────────────────────────────────────────
@router.post("/experimental/mind-map/{book_id}")
async def ai_mind_map(book_id: str) -> dict[str, Any]:
    """Generate AI mind map from book content."""
    from brainycat.experimental.mind_map import generate_mind_map

    return await generate_mind_map(book_id)


# ── Experimental: Share Card ──────────────────────────────────────────────
@router.post("/experimental/share-card")
async def share_card(body: dict[str, Any] | None = None) -> Any:
    """Generate SVG share card from a highlight."""
    from fastapi.responses import Response

    from brainycat.experimental.share_cards import generate_card_svg

    body = body or {}
    svg = generate_card_svg(
        text=body.get("text", ""),
        book_title=body.get("book_title", ""),
        author=body.get("author", ""),
        theme=body.get("theme", "dark"),
    )
    return Response(content=svg, media_type="image/svg+xml")


# ── Experimental: PDF Embed Annotations ───────────────────────────────────
@router.post("/experimental/pdf-embed/{book_id}")
async def pdf_embed(book_id: str) -> dict[str, Any]:
    """Write annotations INTO the PDF file (permanent)."""
    from brainycat.experimental.pdf_embed_annotations import embed_annotations

    return await embed_annotations(book_id)


# ── Calibre Library Import ────────────────────────────────────────────────
@router.post("/import/calibre")
async def import_calibre(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Import books from a Calibre library folder."""
    body = body or {}
    path = body.get("path", "/data/calibre")
    limit = body.get("limit", 100)
    from brainycat.calibre_import import import_calibre_library

    return await import_calibre_library(path, limit)


# ── Readarr Search ────────────────────────────────────────────────────────
@router.post("/readarr/search")
async def readarr_search(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Search Readarr for a book."""
    body = body or {}
    from brainycat.experimental.readarr import search_readarr

    return await search_readarr(body.get("query", ""))


# ── Kindle Clippings Import ───────────────────────────────────────────────
@router.post("/import/kindle-clippings")
async def import_kindle_clippings(body: dict[str, Any] | None = None, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import Kindle My Clippings.txt content."""
    body = body or {}
    text = body.get("text", "")
    if not text:
        return {"error": "provide 'text' field with My Clippings.txt content"}
    from brainycat.kindle_clippings import import_clippings

    return await import_clippings(text, str(user["id"]))


# ── Book DNA / Wrapped ────────────────────────────────────────────────────
@router.get("/wrapped/{year}")
async def reading_wrapped(year: int, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Spotify Wrapped-style yearly reading summary."""
    from brainycat.experimental.book_dna import generate_wrapped

    return await generate_wrapped(str(user["id"]), year)
