"""FastAPI application — all routes for BrainyCat."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from brainycat import (
    auth,
    books,
    collections,
    companion,
    convert,
    db,
    intelligence,
    metadata,
    opds,
    podcast,
    recommendations,
    restoration,
    reviews,
    scanner,
    stats,
    stt,
    sync,
    translation,
    tts,
)
from brainycat.auth import get_current_user, require_admin
from brainycat.jobs import get_job
from brainycat.logging import setup_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    await db.get_pool()
    await auth.seed_users()
    from brainycat.scheduler import start_scheduler

    await start_scheduler()
    yield
    await db.close_pool()


app = FastAPI(title="BrainyCat", version="0.1.0", lifespan=lifespan)


@app.get("/")
async def root() -> RedirectResponse:
    """Redirect root to the static UI. Uses './' so browsers resolve relative to request path."""
    return RedirectResponse(url="./static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Health ────────────────────────────────────────────────────────────────
@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    s = await db.health_check()
    return {"status": "ok" if s.get("connected") else "degraded", "db": s}


# ── Auth ──────────────────────────────────────────────────────────────────
app.post("/api/v1/login")(auth.login)
app.post("/api/v1/logout")(auth.logout)
app.get("/api/v1/me")(auth.me)
app.get("/api/v1/users")(auth.list_users)
app.patch("/api/v1/users/{user_id}")(auth.update_user)
app.patch("/api/v1/me/preferences")(auth.update_preferences)

# ── Books CRUD ────────────────────────────────────────────────────────────
app.post("/api/v1/books/upload")(books.upload_book)
app.get("/api/v1/books")(books.list_books)
app.get("/api/v1/books/{book_id}")(books.get_book)
app.patch("/api/v1/books/{book_id}")(books.update_book)
app.delete("/api/v1/books/{book_id}")(books.delete_book)
app.get("/api/v1/books/{book_id}/cover")(books.serve_cover)
app.get("/api/v1/books/{book_id}/file/{file_id}")(books.serve_file)


# ── Author update
class AuthorUpdate(BaseModel):
    author: str


@app.put("/api/v1/books/{book_id}/author")
async def update_author(book_id: str, body: AuthorUpdate, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID as _UUID

    # Remove old author links
    await db.execute("DELETE FROM books_authors WHERE book_id = $1", _UUID(book_id))
    # Add new author
    author_name = body.author.strip()
    if author_name:
        await db.execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", author_name)
        ar = await db.fetch_one("SELECT id FROM authors WHERE name = $1", author_name)
        if ar:
            await db.execute(
                "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", _UUID(book_id), ar["id"]
            )
    return {"ok": True}


# ── Collections ───────────────────────────────────────────────────────────
app.post("/api/v1/collections")(collections.create_collection)
app.get("/api/v1/collections")(collections.list_collections)
app.post("/api/v1/collections/{collection_id}/books/{book_id}")(collections.add_book_to_collection)
app.delete("/api/v1/collections/{collection_id}/books/{book_id}")(collections.remove_book_from_collection)
app.post("/api/v1/books/{book_id}/link")(collections.link_books)


# ── Metadata enrichment ──────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/enrich")
async def enrich(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await metadata.enrich_book(book_id)


# ── Incoming scanner ─────────────────────────────────────────────────────
@app.get("/api/v1/incoming")
async def list_incoming(status: str | None = Query(None), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await scanner.list_incoming(status)


@app.post("/api/v1/incoming/scan")
async def trigger_scan(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await scanner.scan_incoming()


@app.post("/api/v1/incoming/{item_id}/confirm")
async def confirm(item_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await scanner.confirm_incoming(item_id)


@app.post("/api/v1/incoming/{item_id}/reject")
async def reject(item_id: str, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    return await scanner.reject_incoming(item_id)


# ── Intelligence ─────────────────────────────────────────────────────────
@app.get("/api/v1/intelligence/quality")
async def intel_quality(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.quality_report()


@app.get("/api/v1/intelligence/series-gaps")
async def intel_gaps(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.series_suggestions()


@app.get("/api/v1/intelligence/duplicates")
async def intel_dupes(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.find_duplicates()


@app.get("/api/v1/intelligence/author-suggestions")
async def intel_authors(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.author_suggestions()


class CreateSeriesBody(BaseModel):
    series_name: str
    book_ids: list[str]


@app.post("/api/v1/intelligence/apply-series")
async def intel_apply_series(body: CreateSeriesBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_create_series(body.series_name, body.book_ids)


class MergeAuthorsBody(BaseModel):
    keep_id: str
    merge_id: str


@app.post("/api/v1/intelligence/merge-authors")
async def intel_merge(body: MergeAuthorsBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_merge_authors(body.keep_id, body.merge_id)


class LinkDuplicateBody(BaseModel):
    book_a_id: str
    book_b_id: str
    link_type: str = "edition"


@app.post("/api/v1/intelligence/link-duplicate")
async def intel_link_dup(body: LinkDuplicateBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_link_duplicate(body.book_a_id, body.book_b_id, body.link_type)


class BatchActionsBody(BaseModel):
    actions: list[dict[str, Any]]


@app.post("/api/v1/intelligence/batch")
async def intel_batch(body: BatchActionsBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_batch(body.actions)


# ── Progress, bookmarks, annotations ─────────────────────────────────────
class ProgressUpdate(BaseModel):
    position: str | None = None
    position_timestamp: float | None = None
    percentage: float = 0
    is_finished: bool = False


@app.put("/api/v1/progress/{book_id}")
async def save_progress(book_id: str, body: ProgressUpdate, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from uuid import UUID

    await db.execute(
        """INSERT INTO reading_progress (user_id, book_id, position, position_timestamp, percentage, is_finished, updated_at)
           VALUES ($1,$2,$3,$4,$5,$6,now())
           ON CONFLICT (user_id, book_id) DO UPDATE SET position=$3, position_timestamp=$4, percentage=$5, is_finished=$6, updated_at=now()""",
        user["id"],
        UUID(book_id),
        body.position,
        body.position_timestamp,
        body.percentage,
        body.is_finished,
    )
    return {"ok": True}


@app.get("/api/v1/progress/{book_id}")
async def get_progress(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID

    row = await db.fetch_one("SELECT * FROM reading_progress WHERE user_id = $1 AND book_id = $2", user["id"], UUID(book_id))
    return dict(row) if row else {}


class BookmarkCreate(BaseModel):
    position: str
    title: str | None = None


@app.post("/api/v1/bookmarks/{book_id}")
async def add_bookmark(book_id: str, body: BookmarkCreate, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from uuid import UUID

    await db.execute(
        "INSERT INTO bookmarks (user_id, book_id, position, title) VALUES ($1,$2,$3,$4)",
        user["id"],
        UUID(book_id),
        body.position,
        body.title,
    )
    return {"ok": True}


@app.get("/api/v1/bookmarks/{book_id}")
async def get_bookmarks(book_id: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from uuid import UUID

    rows = await db.fetch_all("SELECT * FROM bookmarks WHERE user_id = $1 AND book_id = $2 ORDER BY created_at", user["id"], UUID(book_id))
    return [dict(r) for r in rows]


class AnnotationCreate(BaseModel):
    cfi_range: str
    text_content: str | None = None
    note: str | None = None
    color: str = "#ffeb3b"


@app.post("/api/v1/annotations/{book_id}")
async def add_annotation(book_id: str, body: AnnotationCreate, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from uuid import UUID

    await db.execute(
        "INSERT INTO annotations (user_id, book_id, cfi_range, text_content, note, color) VALUES ($1,$2,$3,$4,$5,$6)",
        user["id"],
        UUID(book_id),
        body.cfi_range,
        body.text_content,
        body.note,
        body.color,
    )
    return {"ok": True}


@app.get("/api/v1/annotations/{book_id}")
async def get_annotations(book_id: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from uuid import UUID

    rows = await db.fetch_all(
        "SELECT * FROM annotations WHERE user_id = $1 AND book_id = $2 ORDER BY created_at", user["id"], UUID(book_id)
    )
    return [dict(r) for r in rows]


# ── Audio restoration ────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/audio/diagnose")
async def audio_diagnose(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID

    f = await db.fetch_one("SELECT id FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac') LIMIT 1", UUID(book_id))
    if not f:
        return {"error": "No audio file"}
    return await restoration.diagnose(str(f["id"]))


@app.post("/api/v1/books/{book_id}/audio/restore")
async def audio_restore(book_id: str, profile: str = Query("digital_light"), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID

    f = await db.fetch_one("SELECT id FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac') LIMIT 1", UUID(book_id))
    if not f:
        return {"error": "No audio file"}
    return await restoration.restore(str(f["id"]), profile)


@app.post("/api/v1/books/{book_id}/audio/preview")
async def audio_preview(book_id: str, profile: str = Query("digital_light"), _u: Any = Depends(get_current_user)) -> Any:
    from uuid import UUID

    f = await db.fetch_one("SELECT id FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac') LIMIT 1", UUID(book_id))
    if not f:
        return {"error": "No audio file"}
    path = await restoration.preview(str(f["id"]), profile)
    if path:
        return FileResponse(path, media_type="audio/mpeg")
    return {"error": "Preview failed"}


# ── TTS / STT / Convert ─────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/convert/tts")
async def convert_tts(book_id: str, voice: str = Query("en_US-lessac-medium"), user: Any = Depends(get_current_user)) -> dict[str, str]:
    job_id = await tts.convert_to_audiobook(book_id, voice, str(user["id"]))
    return {"job_id": job_id}


@app.post("/api/v1/books/{book_id}/convert/stt")
async def convert_stt(book_id: str, model: str = Query("small"), user: Any = Depends(get_current_user)) -> dict[str, str]:
    job_id = await stt.transcribe_audiobook(book_id, model, str(user["id"]))
    return {"job_id": job_id}


@app.post("/api/v1/books/{book_id}/convert/{target_format}")
async def convert_format(book_id: str, target_format: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await convert.convert_format(book_id, target_format)


@app.get("/api/v1/tts/voices")
async def tts_voices() -> list[dict[str, str]]:
    return await tts.list_voices()


@app.get("/api/v1/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    j = await get_job(job_id)
    return j or {"error": "not found"}


# ── Kindle / device delivery ─────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/send-to-kindle")
async def kindle(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await convert.send_to_kindle(book_id, str(user["id"]))


@app.post("/api/v1/books/{book_id}/send-to-device")
async def device(book_id: str, email: str = Query(...), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await convert.send_to_device(book_id, email)


# ── Catalog (Gutenberg + LibriVox) ───────────────────────────────────────
@app.get("/api/v1/catalog/gutenberg/search")
async def gutenberg_search(
    q: str = Query(""), language: str = Query("en"), page: int = Query(1), _u: Any = Depends(get_current_user)
) -> Any:
    from brainycat.sources.gutendex import browse, search

    if q:
        return await search(title=q, language=language)
    return await browse(language=language, page=page)


@app.get("/api/v1/catalog/gutenberg/{gutenberg_id}")
async def gutenberg_detail(gutenberg_id: int, _u: Any = Depends(get_current_user)) -> Any:
    from brainycat.sources.gutendex import get_book

    return await get_book(gutenberg_id)


@app.post("/api/v1/catalog/gutenberg/{gutenberg_id}/import")
async def gutenberg_import(gutenberg_id: int, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID, uuid4

    import httpx

    from brainycat.sources.gutendex import get_book as gb
    from brainycat.storage import book_dir

    data = await gb(gutenberg_id)
    if not data or not data.get("epub_url"):
        return {"error": "No EPUB available"}
    async with httpx.AsyncClient(timeout=30) as client:
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


@app.get("/api/v1/catalog/librivox/search")
async def librivox_search(title: str = Query(""), author: str = Query(""), _u: Any = Depends(get_current_user)) -> Any:
    from brainycat.sources.librivox import search

    return await search(title=title or None, author=author or None)


# ── Translation ──────────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/translate")
async def translate(
    book_id: str, target_lang: str = Query(...), backend: str = Query("argos"), user: Any = Depends(get_current_user)
) -> dict[str, str]:
    job_id = await translation.translate_book(book_id, target_lang, backend, str(user["id"]))
    return {"job_id": job_id}


@app.get("/api/v1/translation/backends")
async def translation_backends() -> list[dict[str, Any]]:
    return await translation.list_backends()


# ── Sync ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/sync/map/{book_id}")
async def sync_map(book_id: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await sync.get_sync_map(book_id)


@app.get("/api/v1/sync/position/{book_id}")
async def sync_position(
    book_id: str, from_type: str = Query("text"), position: str = Query("0"), _u: Any = Depends(get_current_user)
) -> dict[str, Any]:
    return await sync.translate_position(book_id, from_type, position)


# ── Recommendations ──────────────────────────────────────────────────────
@app.get("/api/v1/recommendations/profile")
async def reco_profile(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await recommendations.build_profile(str(user["id"]))


@app.get("/api/v1/recommendations/{category}")
async def reco_category(category: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await recommendations.get_recommendations(str(user["id"]), category)


# ── AI Companion ─────────────────────────────────────────────────────────
@app.get("/api/v1/ai/recap/{book_id}")
async def ai_recap(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, str]:
    return await companion.recap(book_id, str(user["id"]))


@app.post("/api/v1/ai/ask/{book_id}")
async def ai_ask(book_id: str, question: str = Query(...), user: Any = Depends(get_current_user)) -> dict[str, str]:
    return await companion.ask(book_id, str(user["id"]), question)


@app.post("/api/v1/ai/auto-tag/{book_id}")
async def ai_tag(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await companion.auto_tag(book_id)


# ── Reviews ──────────────────────────────────────────────────────────────
@app.get("/api/v1/books/{book_id}/reviews")
async def book_reviews(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await reviews.get_reviews(book_id)


# ── Stats & Notes ────────────────────────────────────────────────────────
@app.get("/api/v1/stats/overview")
async def stats_overview(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await stats.get_stats(str(user["id"]))


@app.get("/api/v1/books/{book_id}/notes")
async def get_note(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await stats.get_note(str(user["id"]), book_id) or {}


class NoteBody(BaseModel):
    content: str


@app.post("/api/v1/books/{book_id}/notes")
async def save_note(book_id: str, body: NoteBody, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await stats.save_note(str(user["id"]), book_id, body.content)


@app.get("/api/v1/notes/export")
async def export_notes(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await stats.export_notes(str(user["id"]))


# ── OPDS ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/opds/catalog.xml")
async def opds_catalog() -> Any:
    return await opds.catalog()


@app.get("/api/v1/opds/search")
async def opds_search(q: str = Query("")) -> Any:
    return await opds.search_opds(q)


# ── Podcast feeds ────────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/podcast-feed")
async def create_podcast(book_id: str, schedule: str = Query("daily"), user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await podcast.create_feed(book_id, str(user["id"]), schedule)


@app.get("/api/v1/feeds/{feed_id}/rss")
async def podcast_rss(feed_id: str) -> Any:
    return await podcast.get_rss(feed_id)


# ── Import ───────────────────────────────────────────────────────────────
@app.post("/api/v1/import/goodreads")
async def import_gr(file: UploadFile, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.importers.calibre import import_goodreads

    content = (await file.read()).decode()
    return await import_goodreads(content)


@app.post("/api/v1/import/audiobookshelf")
async def import_abs(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.importers.calibre import import_audiobookshelf

    return await import_audiobookshelf()


# ── RSS feed ─────────────────────────────────────────────────────────────
@app.get("/api/v1/feed/recent.xml")
async def recent_feed() -> Any:
    from fastapi.responses import Response

    books_list = await db.fetch_all("SELECT id, title, updated_at FROM books ORDER BY created_at DESC LIMIT 20")
    entries = "\n".join(
        f"<entry><id>urn:brainycat:{r['id']}</id><title>{r['title']}</title><updated>{r['updated_at'].isoformat() if r['updated_at'] else ''}</updated></entry>"
        for r in books_list
    )
    xml = f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><id>urn:brainycat:recent</id><title>BrainyCat — Recent</title>{entries}</feed>'
    return Response(content=xml, media_type="application/atom+xml")


# ── Covers ───────────────────────────────────────────────────────────────
@app.post("/api/v1/covers/optimize")
async def optimize_covers(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.covers import optimize_all_covers

    return await optimize_all_covers()


@app.post("/api/v1/covers/generate-missing")
async def gen_covers(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.covers import generate_missing_covers

    return await generate_missing_covers()


# ── OCR ──────────────────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/ocr")
async def ocr_book(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, str]:
    from brainycat.ocr import ocr_pdf

    job_id = await ocr_pdf(book_id, str(user["id"]))
    return {"job_id": job_id}


# ── Metadata download (Calibre-style) ───────────────────────────────────
@app.post("/api/v1/books/{book_id}/download-metadata")
async def download_metadata(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await metadata.enrich_book(book_id)


@app.post("/api/v1/books/{book_id}/download-cover")
async def download_cover(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Download cover from online sources."""
    import os as _os
    from uuid import UUID as _UUID

    import httpx as _httpx

    from brainycat.storage import book_dir as _bd

    row = await db.fetch_one("SELECT * FROM books WHERE id = $1", _UUID(book_id))
    if not row:
        return {"error": "not found"}

    # Try Google Books
    from brainycat.sources.google_books import search as _gs

    r = await _gs(title=row["title"], isbn=row["isbn"])
    if r and r.get("cover_url"):
        async with _httpx.AsyncClient() as client:
            resp = await client.get(r["cover_url"], timeout=15)
            if resp.status_code == 200:
                cover_path = _os.path.join(_bd(book_id), "cover.jpg")
                with open(cover_path, "wb") as f:
                    f.write(resp.content)
                await db.execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, _UUID(book_id))
                return {"ok": True, "source": "google_books"}
    return {"ok": False, "reason": "no cover found"}


# ── Content-based duplicates ─────────────────────────────────────────────
@app.get("/api/v1/intelligence/content-duplicates")
async def content_dupes(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.duplicates import find_content_duplicates

    return await find_content_duplicates()


# ── Batch PDF cover extraction ───────────────────────────────────────────
@app.post("/api/v1/covers/extract-pdf")
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
@app.post("/api/v1/fingerprints/compute")
async def compute_fps(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.fingerprints import compute_all_fingerprints

    return await compute_all_fingerprints(batch_size=50)


@app.post("/api/v1/fingerprints/find-duplicates")
async def find_fp_dupes(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.fingerprints import find_duplicates_by_content

    return await find_duplicates_by_content(batch_size=100)


@app.get("/api/v1/fingerprints/matches")
async def get_fp_matches(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.fingerprints import get_duplicate_matches

    return await get_duplicate_matches()


@app.post("/api/v1/fingerprints/matches/{match_id}/{action}")
async def resolve_fp_match(match_id: str, action: str, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    from brainycat.fingerprints import resolve_match

    return await resolve_match(match_id, action)


@app.get("/api/v1/fingerprints/status")
async def fp_status(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    total = await db.fetch_one("SELECT count(*) as n FROM book_fingerprints")
    pending_fp = await db.fetch_one("""
        SELECT count(*) as n FROM books b JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
    """)
    pending_matches = await db.fetch_one("SELECT count(*) as n FROM duplicate_matches WHERE status = 'pending'")
    return {
        "fingerprinted": total["n"] if total else 0,
        "pending_fingerprint": pending_fp["n"] if pending_fp else 0,
        "pending_matches": pending_matches["n"] if pending_matches else 0,
    }


# ── LibriVox import ──────────────────────────────────────────────────────
@app.post("/api/v1/catalog/librivox/{librivox_id}/import")
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


# ── Genre classification ─────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/classify")
async def classify_book(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.metadata import classify_genre_via_llm

    return await classify_genre_via_llm(book_id)


# ── PDF generation for Kindle ────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/generate-pdf")
async def generate_pdf(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Generate a clean, annotatable PDF from EPUB or optimize existing PDF for Kindle."""
    from uuid import UUID as _UUID
    from uuid import uuid4 as _uuid4

    from brainycat.storage import book_dir as _bd

    # Check if we already have a PDF
    pdf_row = await db.fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1", _UUID(book_id))
    if pdf_row and os.path.isfile(pdf_row["file_path"]):
        import fitz

        # Optimize existing PDF: linearize for fast web view, ensure annotations allowed
        src = pdf_row["file_path"]
        dest = src.replace(".pdf", "_kindle.pdf")
        try:
            doc = fitz.open(src)
            # Remove restrictions if any
            doc.save(dest, deflate=True, garbage=4, linear=True)
            doc.close()
            if os.path.isfile(dest):
                fid = _uuid4()
                await db.execute(
                    """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size, mime_type)
                       VALUES ($1,$2,'pdf',$3,$4,$5,'application/pdf')""",
                    fid,
                    _UUID(book_id),
                    dest,
                    "kindle_" + os.path.basename(src),
                    os.path.getsize(dest),
                )
                return {"ok": True, "file_id": str(fid), "method": "optimized_pdf", "size": os.path.getsize(dest)}
        except Exception as e:
            return {"error": f"PDF optimization failed: {e}"}

    # No PDF — generate from EPUB via WeasyPrint (proper HTML/CSS rendering)
    epub_row = await db.fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", _UUID(book_id))
    if not epub_row:
        return {"error": "No EPUB or PDF source file"}

    try:
        import ebooklib
        import weasyprint
        from ebooklib import epub

        ebook = epub.read_epub(epub_row["file_path"], options={"ignore_ncx": True})
        html_parts = []
        for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            html_parts.append(item.get_content().decode(errors="replace"))

        css = "body{font-family:serif;font-size:11pt;line-height:1.6;margin:2cm}h1,h2,h3{page-break-before:always}img{max-width:100%;height:auto}"
        full_html = "<html><head><style>" + css + "</style></head><body>" + "\n".join(html_parts) + "</body></html>"
        pdf_bytes = weasyprint.HTML(string=full_html).write_pdf()

        dest = os.path.join(_bd(book_id), "kindle.pdf")
        with open(dest, "wb") as out:
            out.write(pdf_bytes)

        fid = _uuid4()
        size = os.path.getsize(dest)
        await db.execute(
            """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size, mime_type)
               VALUES ($1,$2,'pdf',$3,'kindle.pdf',$4,'application/pdf')""",
            fid,
            _UUID(book_id),
            dest,
            size,
        )
        return {"ok": True, "file_id": str(fid), "method": "epub_to_pdf_weasyprint", "size": size}
    except Exception as e:
        return {"error": f"PDF generation failed: {e}"}


# ── ISBN extraction ──────────────────────────────────────────────────────
@app.post("/api/v1/isbn/extract")
async def extract_isbns(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.isbn import batch_extract_isbns

    return await batch_extract_isbns(limit=100)


@app.post("/api/v1/books/{book_id}/extract-isbn")
async def extract_book_isbn(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.isbn import extract_and_store_isbn

    return await extract_and_store_isbn(book_id)


# ── Enrichment stats ─────────────────────────────────────────────────────
@app.get("/api/v1/intelligence/enrichment-stats")
async def enrichment_stats(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Enrichment activity by method over time periods."""
    rows = await db.fetch_all("""
        SELECT method,
            count(*) FILTER (WHERE success AND created_at > now() - interval '1 hour') as success_1h,
            count(*) FILTER (WHERE NOT success AND created_at > now() - interval '1 hour') as fail_1h,
            count(*) FILTER (WHERE success AND created_at > now() - interval '24 hours') as success_24h,
            count(*) FILTER (WHERE NOT success AND created_at > now() - interval '24 hours') as fail_24h,
            count(*) FILTER (WHERE success AND created_at > now() - interval '7 days') as success_7d,
            count(*) FILTER (WHERE success AND created_at > now() - interval '30 days') as success_30d
        FROM enrichment_log
        GROUP BY method ORDER BY method
    """)
    return {
        "methods": [
            {
                "method": r["method"],
                "1h": {"success": r["success_1h"], "fail": r["fail_1h"]},
                "24h": {"success": r["success_24h"], "fail": r["fail_24h"]},
                "7d": r["success_7d"],
                "30d": r["success_30d"],
            }
            for r in rows
        ],
        "totals": {
            "with_isbn": (await db.fetch_one("SELECT count(*) as n FROM books WHERE isbn IS NOT NULL AND isbn != ''"))["n"],
            "enriched": (await db.fetch_one("SELECT count(*) as n FROM books WHERE quality_score > 0"))["n"],
            "total": (await db.fetch_one("SELECT count(*) as n FROM books"))["n"],
            "in_series": (await db.fetch_one("SELECT count(DISTINCT book_id) as n FROM books_series"))["n"],
            "series_count": (await db.fetch_one("SELECT count(*) as n FROM series"))["n"],
            "fingerprinted": (await db.fetch_one("SELECT count(*) as n FROM book_fingerprints"))["n"],
        },
    }


# ── Workbook flag ────────────────────────────────────────────────────────
@app.patch("/api/v1/books/{book_id}/workbook")
async def toggle_workbook(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID as _UUID

    row = await db.fetch_one("SELECT is_workbook FROM books WHERE id = $1", _UUID(book_id))
    new_val = not (row["is_workbook"] if row else False)
    await db.execute("UPDATE books SET is_workbook = $1 WHERE id = $2", new_val, _UUID(book_id))
    return {"is_workbook": new_val}


# ── Metadata writeback ───────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/writeback")
async def writeback(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.writeback import writeback_metadata

    return await writeback_metadata(book_id)


@app.post("/api/v1/writeback/batch")
async def batch_wb(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.writeback import batch_writeback

    return await batch_writeback(limit=50)


# ── Efficiency dashboard ─────────────────────────────────────────────────
@app.get("/api/v1/intelligence/efficiency")
async def efficiency_dashboard(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Comprehensive efficiency metrics for all algorithms."""
    # ISBN pipeline
    isbn_stats = await db.fetch_one("""
        SELECT
            count(*) FILTER (WHERE isbn IS NOT NULL AND isbn != '') as with_isbn,
            count(*) FILTER (WHERE isbn IS NULL OR isbn = '') as without_isbn,
            count(*) FILTER (WHERE quality_score >= 75) as high_quality,
            count(*) FILTER (WHERE quality_score BETWEEN 50 AND 74) as medium_quality,
            count(*) FILTER (WHERE quality_score BETWEEN 1 AND 49) as low_quality,
            count(*) FILTER (WHERE quality_score = 0) as not_enriched,
            count(*) as total
        FROM books
    """)

    # ISBN → enrichment success rate
    isbn_to_enrich = await db.fetch_one("""
        SELECT
            count(DISTINCT el.book_id) FILTER (WHERE el.success AND b.isbn IS NOT NULL) as isbn_led_to_data,
            count(DISTINCT el.book_id) FILTER (WHERE NOT el.success AND b.isbn IS NOT NULL) as isbn_no_data,
            count(DISTINCT el.book_id) FILTER (WHERE el.success AND b.isbn IS NULL) as no_isbn_got_data,
            count(DISTINCT el.book_id) FILTER (WHERE NOT el.success AND b.isbn IS NULL) as no_isbn_no_data
        FROM enrichment_log el
        JOIN books b ON b.id = el.book_id
    """)

    # Per-source hit rates
    source_stats = await db.fetch_all("""
        SELECT method,
            count(*) FILTER (WHERE success) as hits,
            count(*) FILTER (WHERE NOT success) as misses,
            count(*) as total,
            CASE WHEN count(*) > 0 THEN round(100.0 * count(*) FILTER (WHERE success) / count(*), 1) ELSE 0 END as hit_rate
        FROM enrichment_log
        WHERE method NOT IN ('writeback', 'isbn_extract', 'series_detect')
        GROUP BY method ORDER BY hit_rate DESC
    """)

    # Fingerprint progress
    fp_stats = await db.fetch_one("""
        SELECT
            (SELECT count(*) FROM book_fingerprints) as fingerprinted,
            (SELECT count(*) FROM duplicate_matches WHERE status = 'pending') as pending_dupes,
            (SELECT count(*) FROM duplicate_matches WHERE status = 'confirmed') as confirmed_dupes,
            (SELECT count(*) FROM duplicate_matches WHERE status = 'dismissed') as dismissed_dupes
    """)

    # Series
    series_stats = await db.fetch_one("""
        SELECT
            (SELECT count(*) FROM series) as series_count,
            (SELECT count(DISTINCT book_id) FROM books_series) as books_in_series
    """)

    # Writeback
    wb_stats = await db.fetch_one("""
        SELECT count(*) FILTER (WHERE success) as written_back
        FROM enrichment_log WHERE method = 'writeback'
    """)

    # Cover stats
    cover_stats = await db.fetch_one("""
        SELECT
            count(*) FILTER (WHERE cover_path IS NOT NULL) as with_cover,
            count(*) FILTER (WHERE cover_path IS NULL) as without_cover
        FROM books
    """)

    return {
        "isbn": dict(isbn_stats) if isbn_stats else {},
        "isbn_effectiveness": dict(isbn_to_enrich) if isbn_to_enrich else {},
        "sources": [dict(r) for r in source_stats],
        "fingerprints": dict(fp_stats) if fp_stats else {},
        "series": dict(series_stats) if series_stats else {},
        "writeback": {"written_back": wb_stats["written_back"] if wb_stats else 0},
        "covers": dict(cover_stats) if cover_stats else {},
    }
