"""FastAPI application — all routes for BrainyCat."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
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

# ABS mobile app compatibility
from brainycat.abs_compat import router as abs_router  # noqa: E402

app.include_router(abs_router)


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
    from brainycat.format_convert import convert_book

    return await convert_book(book_id, target_format)


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
async def opds_catalog(page: int = Query(1)) -> Any:
    return await opds.catalog(page)


@app.get("/api/v1/opds/search")
async def opds_search(q: str = Query(""), page: int = Query(1)) -> Any:
    return await opds.search_opds(q, page)


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


# ── Bilingual content ────────────────────────────────────────────────────
@app.get("/api/v1/books/{book_id}/bilingual")
async def bilingual_content(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get aligned original + translated paragraphs for bilingual reading."""
    from uuid import UUID as _UUID

    # Find translation link
    trans = await db.fetch_one(
        """
        SELECT bt.*, bl.book_b_id as trans_book_id
        FROM book_translations bt
        JOIN book_links bl ON bl.book_a_id = bt.source_book_id AND bl.book_b_id = bt.target_book_id
        WHERE bt.source_book_id = $1
        LIMIT 1
    """,
        _UUID(book_id),
    )

    if not trans:
        # Try reverse
        trans = await db.fetch_one(
            """
            SELECT bt.*, bl.book_a_id as trans_book_id
            FROM book_translations bt
            JOIN book_links bl ON bl.book_a_id = bt.target_book_id AND bl.book_b_id = bt.source_book_id
            WHERE bt.target_book_id = $1
            LIMIT 1
        """,
            _UUID(book_id),
        )

    if not trans:
        return {"error": "No translation found. Use the Translate feature first.", "paragraphs": []}

    # Load both EPUBs and extract paragraphs
    orig_file = await db.fetch_one("SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", _UUID(book_id))
    trans_file = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", trans["trans_book_id"]
    )

    if not orig_file or not trans_file:
        return {"error": "Missing EPUB files", "paragraphs": []}

    orig_paras = _extract_paragraphs(orig_file["file_path"])
    trans_paras = _extract_paragraphs(trans_file["file_path"])

    # Align by index (translation preserves paragraph structure)
    aligned = []
    for i in range(max(len(orig_paras), len(trans_paras))):
        aligned.append(
            {
                "index": i,
                "original": orig_paras[i] if i < len(orig_paras) else "",
                "translated": trans_paras[i] if i < len(trans_paras) else "",
            }
        )

    return {
        "source_language": trans["source_language"],
        "target_language": trans["target_language"],
        "backend": trans["backend"],
        "total_paragraphs": len(aligned),
        "paragraphs": aligned,
    }


def _extract_paragraphs(epub_path: str) -> list[str]:
    """Extract all paragraphs from an EPUB."""
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(epub_path, options={"ignore_ncx": True})
        paragraphs = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for p in soup.find_all("p"):
                text = p.get_text(strip=True)
                if text and len(text) > 5:
                    paragraphs.append(text)
        return paragraphs
    except Exception:
        return []


# ── Embeddings & Similar Books ───────────────────────────────────────────
@app.post("/api/v1/embeddings/generate")
async def gen_embeddings(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.embeddings import embed_all_books

    return await embed_all_books(limit=100)


@app.get("/api/v1/books/{book_id}/similar")
async def similar_books(book_id: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.embeddings import find_similar

    return await find_similar(book_id)


# ── Real-time activity (WebSocket) ───────────────────────────────────────

_active_readers: dict[str, dict[str, Any]] = {}  # user_id → {book_id, title, percentage, updated}


@app.websocket("/api/v1/ws/activity")
async def ws_activity(websocket: WebSocket) -> None:
    """WebSocket for real-time reading activity feed."""
    await websocket.accept()
    import asyncio
    import json

    try:
        while True:
            # Send current activity every 5 seconds
            activity = [{"user": uid, **data} for uid, data in _active_readers.items()]
            await websocket.send_text(json.dumps({"type": "activity", "readers": activity}))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass


@app.post("/api/v1/activity/reading")
async def report_reading(book_id: str = Query(...), percentage: float = Query(0), user: Any = Depends(get_current_user)) -> dict[str, bool]:
    """Report current reading position for activity feed."""
    import datetime

    book = await db.fetch_one("SELECT title FROM books WHERE id = $1", __import__("uuid").UUID(book_id))
    _active_readers[user["username"]] = {
        "book_id": book_id,
        "title": book["title"] if book else "Unknown",
        "percentage": round(percentage, 1),
        "updated": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    return {"ok": True}


# ── Collaborative annotations ────────────────────────────────────────────
@app.get("/api/v1/books/{book_id}/shared-annotations")
async def shared_annotations(book_id: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get all shared annotations for a book (from all users)."""
    from uuid import UUID as _UUID

    rows = await db.fetch_all(
        """
        SELECT a.*, u.username FROM annotations a
        JOIN users u ON u.id = a.user_id
        WHERE a.book_id = $1 AND a.is_shared = true
        ORDER BY a.created_at
    """,
        _UUID(book_id),
    )
    return [dict(r) for r in rows]


@app.patch("/api/v1/annotations/{annotation_id}/share")
async def toggle_share(annotation_id: str, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    """Toggle sharing of an annotation."""
    from uuid import UUID as _UUID

    row = await db.fetch_one("SELECT is_shared FROM annotations WHERE id = $1", _UUID(annotation_id))
    new_val = not (row["is_shared"] if row else False)
    await db.execute("UPDATE annotations SET is_shared = $1 WHERE id = $2", new_val, _UUID(annotation_id))
    return {"is_shared": new_val}


# ── Activity feed ────────────────────────────────────────────────────────
@app.get("/api/v1/activity/feed")
async def activity_feed(limit: int = Query(20), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Recent activity across all users."""
    rows = await db.fetch_all(
        """
        SELECT al.*, u.username, b.title as book_title
        FROM activity_log al
        JOIN users u ON u.id = al.user_id
        LEFT JOIN books b ON b.id = al.book_id
        ORDER BY al.created_at DESC LIMIT $1
    """,
        limit,
    )
    return [dict(r) for r in rows]


# ── AI Companion (updated) ───────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/index-content")
async def index_content(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.companion import index_book_content

    return await index_book_content(book_id)


@app.get("/api/v1/books/{book_id}/search-content")
async def search_content(book_id: str, q: str = Query(...), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.companion import semantic_search

    return await semantic_search(book_id, q)


# ── Page/word count ──────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/count-pages")
async def count_pages(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Count pages and words in a book."""
    from uuid import UUID as _UUID

    row = await db.fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 AND format IN ('epub','pdf') LIMIT 1", _UUID(book_id)
    )
    if not row:
        return {"error": "no file"}
    pages, words = 0, 0
    try:
        if row["format"] == "pdf":
            import fitz

            doc = fitz.open(row["file_path"])
            pages = len(doc)
            for page in doc:
                words += len(page.get_text().split())
            doc.close()
        elif row["format"] == "epub":
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator=" ", strip=True)
                words += len(text.split())
            pages = max(1, words // 250)  # ~250 words per page
    except Exception as e:
        return {"error": str(e)[:100]}
    minutes = max(1, words // 250)  # ~250 wpm reading speed
    await db.execute(
        "UPDATE books SET word_count=$1, page_count=$2, estimated_reading_minutes=$3 WHERE id=$4", words, pages, minutes, _UUID(book_id)
    )
    return {"words": words, "pages": pages, "estimated_minutes": minutes}


@app.post("/api/v1/count-pages/batch")
async def batch_count(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Count pages for books that don't have counts yet."""
    rows = await db.fetch_all("SELECT b.id FROM books b WHERE b.word_count IS NULL LIMIT 50")
    counted = 0
    for r in rows:
        result = await count_pages(str(r["id"]))
        if result.get("words"):
            counted += 1
    return {"counted": counted, "batch": len(rows)}


# ── Bulk operations ──────────────────────────────────────────────────────
class BulkTagBody(BaseModel):
    book_ids: list[str]
    tag: str
    action: str = "add"  # add or remove


@app.post("/api/v1/bulk/tag")
async def bulk_tag(body: BulkTagBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add or remove a tag from multiple books."""
    from uuid import UUID as _UUID

    await db.execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", body.tag)
    tag_row = await db.fetch_one("SELECT id FROM tags WHERE name = $1", body.tag)
    if not tag_row:
        return {"error": "tag creation failed"}
    applied = 0
    for bid in body.book_ids:
        if body.action == "add":
            await db.execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", _UUID(bid), tag_row["id"])
        else:
            await db.execute("DELETE FROM books_tags WHERE book_id = $1 AND tag_id = $2", _UUID(bid), tag_row["id"])
        applied += 1
    return {"applied": applied, "tag": body.tag, "action": body.action}


class BulkEnrichBody(BaseModel):
    book_ids: list[str]


@app.post("/api/v1/bulk/enrich")
async def bulk_enrich(body: BulkEnrichBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Trigger enrichment for multiple books."""
    enriched = 0
    for bid in body.book_ids:
        result = await metadata.enrich_book(bid)
        if result.get("enriched"):
            enriched += 1
    return {"enriched": enriched, "total": len(body.book_ids)}


# ── API Keys ─────────────────────────────────────────────────────────────
@app.post("/api/v1/api-keys")
async def create_api_key(name: str = Query("default"), user: Any = Depends(get_current_user)) -> dict[str, str]:
    """Generate a new API key for the current user."""
    import hashlib
    import secrets

    token = f"bc_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    await db.execute(
        "INSERT INTO api_keys (key_hash, user_id, name) VALUES ($1, $2, $3)",
        key_hash,
        user["id"],
        name,
    )
    return {"api_key": token, "name": name, "note": "Save this key — it cannot be retrieved later"}


@app.get("/api/v1/api-keys")
async def list_api_keys(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List API keys for the current user (hashes only, not the actual keys)."""
    rows = await db.fetch_all("SELECT id, name, created_at FROM api_keys WHERE user_id = $1", user["id"])
    return [dict(r) for r in rows]


@app.delete("/api/v1/api-keys/{key_id}")
async def delete_api_key(key_id: str, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from uuid import UUID as _UUID

    await db.execute("DELETE FROM api_keys WHERE id = $1 AND user_id = $2", _UUID(key_id), user["id"])
    return {"ok": True}


# ── EPUB Quality Check ───────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/epub-check")
async def epub_check(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_check import check_epub

    return await check_epub(book_id)


@app.post("/api/v1/epub-check/batch")
async def batch_epub_check(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    rows = await db.fetch_all("""
        SELECT DISTINCT bf.book_id FROM book_files bf
        JOIN books b ON b.id = bf.book_id
        WHERE bf.format = 'epub' AND (b.quality_score IS NULL OR b.quality_score = 0)
        LIMIT 50
    """)
    checked = 0
    for r in rows:
        from brainycat.epub_check import check_epub

        result = await check_epub(str(r["book_id"]))
        if result.get("score") is not None:
            checked += 1
    return {"checked": checked, "batch": len(rows)}


# ── EPUB Merge/Split ─────────────────────────────────────────────────────
class MergeBody(BaseModel):
    book_ids: list[str]
    title: str
    author: str = ""


@app.post("/api/v1/epub/merge")
async def epub_merge(body: MergeBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_tools import merge_epubs

    return await merge_epubs(body.book_ids, body.title, body.author)


@app.post("/api/v1/books/{book_id}/epub-split")
async def epub_split(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_tools import split_epub

    return await split_epub(book_id)


# ── Embeddings reindex ───────────────────────────────────────────────────
@app.post("/api/v1/embeddings/reindex")
async def reindex_embeddings(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.embeddings import reindex_all

    return await reindex_all()


# ── UI Skin selection ────────────────────────────────────────────────────
@app.get("/api/v1/ui/skins")
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
@app.get("/api/v1/recommendations/{user_id}")
async def taste_recommendations(user_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.taste import get_5cat_recommendations

    return await get_5cat_recommendations(user_id)


@app.get("/api/v1/taste-profile/{user_id}")
async def taste_profile(user_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.taste import build_taste_profile

    return await build_taste_profile(user_id)


# ── Multi-source aggregation ─────────────────────────────────────────────
@app.get("/api/v1/books/{book_id}/sources")
async def book_sources(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.aggregator import aggregate_metadata

    return await aggregate_metadata(book_id)


@app.get("/api/v1/sources/coverage")
async def source_coverage(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.aggregator import library_source_coverage

    return await library_source_coverage()


# ── Calibre import ───────────────────────────────────────────────────────
@app.post("/api/v1/import/calibre")
async def import_calibre(path: str = Query(...), _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.calibre_import import calibre_library_stats, detect_calibre_library

    if not detect_calibre_library(path):
        return {"error": "Not a Calibre library (no metadata.db)"}
    return {"detected": True, "stats": calibre_library_stats(path)}


@app.post("/api/v1/import/calibre/run")
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
@app.post("/api/v1/books/{book_id}/epub-lint")
async def epub_lint(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_lint import lint_epub

    return await lint_epub(book_id)


# ── Goodreads import ─────────────────────────────────────────────────────
@app.post("/api/v1/import/goodreads")
async def import_goodreads(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import Goodreads CSV export. Send CSV as request body."""
    from brainycat.goodreads import import_goodreads_csv

    body = await request.body()
    csv_content = body.decode("utf-8", errors="replace")
    return await import_goodreads_csv(csv_content, str(user["id"]))


# ── Device annotation import ─────────────────────────────────────────────
@app.post("/api/v1/import/kindle-clippings")
async def import_kindle(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import Kindle My Clippings.txt. Send file content as request body."""
    from brainycat.device_import import import_kindle_clippings

    body = await request.body()
    return await import_kindle_clippings(body.decode("utf-8", errors="replace"), str(user["id"]))


@app.post("/api/v1/import/kobo")
async def import_kobo(path: str = Query(...), user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Import annotations from Kobo KoboReader.sqlite."""
    from brainycat.device_import import import_kobo_annotations

    return await import_kobo_annotations(path, str(user["id"]))


# ── WordDumb (Word Wise + X-Ray) ─────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/word-wise")
async def word_wise(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.worddumb import generate_word_wise

    return await generate_word_wise(book_id)


@app.post("/api/v1/books/{book_id}/xray")
async def xray(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.worddumb import generate_xray

    return await generate_xray(book_id)


# ── AZW3 cover extraction ────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/extract-cover")
async def extract_cover(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID as _UUID

    from brainycat.azw3 import extract_azw3_cover

    row = await db.fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 AND format IN ('azw3','mobi','kfx') LIMIT 1",
        _UUID(book_id),
    )
    if not row:
        return {"error": "no AZW3/MOBI/KFX file"}
    cover = extract_azw3_cover(row["file_path"])
    if not cover:
        return {"error": "no cover found in file"}
    cover_path = f"/data/covers/{book_id}.jpg"
    with open(cover_path, "wb") as f:
        f.write(cover)
    await db.execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, _UUID(book_id))
    return {"ok": True, "size": len(cover)}


@app.get("/api/v1/converters")
async def converters(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.format_convert import list_converters

    return await list_converters()


# ── DeACSM ───────────────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/deacsm")
async def deacsm(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Convert an ACSM file associated with a book to DRM-free EPUB/PDF."""
    from uuid import UUID as _UUID

    from brainycat.deacsm import convert_acsm

    row = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'acsm' LIMIT 1",
        _UUID(book_id),
    )
    if not row:
        return {"error": "no .acsm file for this book"}
    return await convert_acsm(row["file_path"], book_id)


# ── Kobo KEPUB ───────────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/convert/kepub")
async def convert_kepub(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.kepub import epub_to_kepub

    return await epub_to_kepub(book_id)


# ── Cover settings ───────────────────────────────────────────────────────
@app.get("/api/v1/cover-settings")
async def get_cover_prefs(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.cover_settings import get_cover_settings

    return await get_cover_settings(str(user["id"]))


@app.post("/api/v1/cover-settings")
async def set_cover_prefs(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.cover_settings import update_cover_settings

    body = await request.json()
    return await update_cover_settings(str(user["id"]), body)


# ── Async jobs ───────────────────────────────────────────────────────────
@app.get("/api/v1/jobs")
async def list_async_jobs(book_id: str = Query(None), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.async_jobs import list_jobs

    return await list_jobs(book_id)


# ── Plugin system ────────────────────────────────────────────────────────
@app.get("/api/v1/plugins")
async def list_plugins(_a: Any = Depends(require_admin)) -> list[dict[str, str]]:
    from brainycat.plugins import get_plugins

    return get_plugins()


# ── Custom columns ───────────────────────────────────────────────────────
@app.get("/api/v1/custom-columns")
async def get_custom_columns(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.custom_columns import list_columns

    return await list_columns()


@app.post("/api/v1/custom-columns")
async def create_custom_column(request: Request, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.custom_columns import create_column

    body = await request.json()
    return await create_column(body["name"], body["label"], body.get("datatype", "text"))


@app.post("/api/v1/books/{book_id}/custom/{column_name}")
async def set_custom_value(book_id: str, column_name: str, request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.custom_columns import set_value

    body = await request.json()
    return await set_value(book_id, column_name, body.get("value"))


# ── Virtual libraries ────────────────────────────────────────────────────
@app.get("/api/v1/virtual-libraries")
async def get_vlibs(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.virtual_libraries import list_virtual_libraries

    return await list_virtual_libraries(str(user["id"]))


@app.post("/api/v1/virtual-libraries")
async def create_vlib(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.virtual_libraries import create_virtual_library

    body = await request.json()
    return await create_virtual_library(str(user["id"]), body["name"], body["query"], body.get("filters"))


@app.delete("/api/v1/virtual-libraries/{vlib_id}")
async def delete_vlib(vlib_id: str, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from brainycat.virtual_libraries import delete_virtual_library

    return await delete_virtual_library(vlib_id, str(user["id"]))


# ── Federated social ─────────────────────────────────────────────────────
@app.post("/api/v1/social/enable-profile")
async def enable_profile(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.social import enable_public_profile

    return await enable_public_profile(str(user["id"]), "tools.ecb.pm/brainycat")


@app.get("/api/v1/social/following")
async def get_following(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.social import list_following

    return await list_following(str(user["id"]))


@app.post("/api/v1/social/follow")
async def follow(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.social import follow_user

    body = await request.json()
    return await follow_user(str(user["id"]), body["hash"])


@app.post("/api/v1/social/refresh")
async def refresh_social(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.social import refresh_follows

    return await refresh_follows(str(user["id"]))


@app.get("/public/{username}/feed.json")
async def public_feed(username: str) -> dict[str, Any]:
    """Public feed endpoint — no auth required, polled by followers."""
    from brainycat.social import get_public_feed

    return await get_public_feed(username)


# ── Book Clubs ───────────────────────────────────────────────────────────
@app.post("/api/v1/clubs")
async def create_book_club(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.book_clubs import create_club

    body = await request.json()
    return await create_club(str(user["id"]), body["name"], body["book_id"], body.get("chapters_per_week", 3), body.get("start_date"))


@app.get("/api/v1/clubs/{club_id}")
async def get_book_club(club_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.book_clubs import get_club

    return await get_club(club_id, str(user["id"]))


@app.post("/api/v1/clubs/{club_id}/join")
async def join_book_club(club_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.book_clubs import join_club

    return await join_club(club_id, str(user["id"]))


@app.post("/api/v1/clubs/{club_id}/discuss")
async def club_discuss(club_id: str, request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.book_clubs import post_discussion

    body = await request.json()
    return await post_discussion(club_id, str(user["id"]), body["chapter"], body["content"])


# ── Sleep Fade ───────────────────────────────────────────────────────────
@app.post("/api/v1/sleep/report")
async def sleep_report(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sleep_fade import report_playback_stop

    body = await request.json()
    return await report_playback_stop(str(user["id"]), body["book_id"], body["position"], body.get("explicit_pause", False))


@app.get("/api/v1/sleep/rewind/{book_id}")
async def sleep_rewind(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sleep_fade import get_rewind_suggestion

    return await get_rewind_suggestion(str(user["id"]), book_id)


# ── Lending ──────────────────────────────────────────────────────────────
@app.post("/api/v1/lending/request")
async def lend_request(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.lending import request_lend

    body = await request.json()
    return await request_lend(str(user["id"]), body["book_id"], body.get("server_url", ""), body.get("owner", ""), body.get("message", ""))


@app.get("/api/v1/lending/incoming")
async def lending_incoming(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.lending import list_incoming_requests

    return await list_incoming_requests(str(user["id"]))


@app.post("/api/v1/lending/{request_id}/approve")
async def lending_approve(request_id: str, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.lending import approve_request

    return await approve_request(request_id, "")


@app.post("/api/v1/lending/{request_id}/deny")
async def lending_deny(request_id: str, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.lending import deny_request

    return await deny_request(request_id)


# ── Streaks & Challenges ─────────────────────────────────────────────────
@app.get("/api/v1/streaks")
async def get_streaks(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.streaks import get_streak

    return await get_streak(str(user["id"]))


@app.get("/api/v1/challenges")
async def get_challenges_list(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.streaks import get_challenges

    return await get_challenges(str(user["id"]))


@app.post("/api/v1/challenges")
async def create_challenge_endpoint(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.streaks import create_challenge

    body = await request.json()
    return await create_challenge(str(user["id"]), body["name"], body["target"], body.get("year"))


# ── Contextual Footnotes ─────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/footnotes")
async def get_footnotes(book_id: str, request: Request, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.footnotes import generate_footnotes

    body = await request.json()
    return await generate_footnotes(book_id, body.get("text", ""), body.get("chapter_idx", 0))


# ── Adaptive chapter splitting ────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/detect-chapters")
async def detect_chapters(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.chapter_split import detect_chapters as _detect

    return await _detect(book_id)


# ── Readability scoring ──────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/readability")
async def book_readability(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.readability import score_book_readability

    return await score_book_readability(book_id)


# ── Edition diffing ──────────────────────────────────────────────────────
@app.post("/api/v1/diff")
async def edition_diff(request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.edition_diff import diff_editions

    body = await request.json()
    return await diff_editions(body["book_a"], body["book_b"])


# ── Gutenberg ↔ LibriVox cross-linking ────────────────────────────────────
@app.get("/api/v1/catalog/crosslink")
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


# ── Catalog cache ─────────────────────────────────────────────────────────
@app.post("/api/v1/catalog/sync/gutenberg")
async def sync_gut(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.catalog_cache import sync_gutenberg

    return await sync_gutenberg()


@app.post("/api/v1/catalog/sync/librivox")
async def sync_lv(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.catalog_cache import sync_librivox

    return await sync_librivox()


@app.post("/api/v1/catalog/sync/crosslinks")
async def sync_crosslinks(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.catalog_cache import compute_crosslinks

    return await compute_crosslinks()


@app.get("/api/v1/catalog/cached")
async def cached_search(
    q: str = Query(""), source: str = Query("gutenberg"), language: str = Query("en"), _u: Any = Depends(get_current_user)
) -> dict[str, Any]:
    from brainycat.catalog_cache import search_cached

    return await search_cached(q, source, language)


# ── User language preferences ─────────────────────────────────────────────
@app.get("/api/v1/settings/languages")
async def get_language_prefs(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    row = await db.fetch_one("SELECT preferences FROM users WHERE id = $1", user["id"])
    prefs = (row["preferences"] or {}) if row else {}
    return {"languages": prefs.get("catalog_languages", ["en", "fr"])}


@app.post("/api/v1/settings/languages")
async def set_language_prefs(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    body = await request.json()
    langs = body.get("languages", ["en", "fr"])
    import json

    await db.execute(
        "UPDATE users SET preferences = jsonb_set(COALESCE(preferences, '{}'), '{catalog_languages}', $1::jsonb) WHERE id = $2",
        json.dumps(langs),
        user["id"],
    )
    return {"languages": langs}


# ── Book summaries (getAbstract-style) ────────────────────────────────────
@app.post("/api/v1/books/{book_id}/summary")
async def book_summary(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.summaries import generate_summary

    return await generate_summary(book_id)


# ── Standard Ebooks catalog ──────────────────────────────────────────────
@app.get("/api/v1/catalog/standard-ebooks/search")
async def standard_ebooks_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> Any:
    from brainycat.sources.standard_ebooks import search

    return await search(q)


# ── GitHub ebook discovery ────────────────────────────────────────────────
@app.get("/api/v1/catalog/github/search")
async def github_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.github_books import search_ebooks

    return await search_ebooks(q)


@app.get("/api/v1/catalog/github/awesome")
async def github_awesome(topic: str = Query("books"), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.github_books import search_awesome_lists

    return await search_awesome_lists(topic)


@app.get("/api/v1/catalog/github/{owner}/{repo}/files")
async def github_files(owner: str, repo: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.github_books import find_epub_files

    return await find_epub_files(owner, repo)


# ── Open textbook sources ─────────────────────────────────────────────────
@app.get("/api/v1/catalog/oapen/search")
async def oapen_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_textbooks import search_oapen

    return await search_oapen(q)


@app.get("/api/v1/catalog/openstax")
async def openstax_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_textbooks import search_openstax

    return await search_openstax(q)


@app.get("/api/v1/catalog/open-textbooks/search")
async def otl_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_textbooks import search_open_textbook_library

    return await search_open_textbook_library(q)


# ── Unified catalog search ────────────────────────────────────────────────
@app.get("/api/v1/catalog/search")
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


# ── Enhanced enrichment sources ───────────────────────────────────────────
@app.get("/api/v1/enrichment/open-library-enhanced")
async def ol_enhanced(title: str = Query(""), isbn: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_library_enhanced import search_enhanced

    return await search_enhanced(title=title or None, isbn=isbn or None) or {}


@app.get("/api/v1/enrichment/viaf")
async def viaf_search(name: str = Query(""), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.authority import search_viaf

    return await search_viaf(name)


@app.get("/api/v1/enrichment/inventaire")
async def inventaire_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.authority import search_inventaire

    return await search_inventaire(q)


@app.get("/api/v1/enrichment/bookbrainz")
async def bookbrainz_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.authority import search_bookbrainz

    return await search_bookbrainz(q)


@app.get("/api/v1/enrichment/sources")
async def enrichment_sources(_u: Any = Depends(get_current_user)) -> list[dict[str, str]]:
    """List all available enrichment sources."""
    return [
        {"id": "google_books", "name": "Google Books", "type": "metadata", "auth": "none"},
        {"id": "open_library", "name": "Open Library (basic)", "type": "metadata", "auth": "none"},
        {"id": "open_library_enhanced", "name": "Open Library (Works + Ratings)", "type": "metadata+ratings", "auth": "none"},
        {"id": "gutendex", "name": "Gutendex (Gutenberg)", "type": "metadata", "auth": "none"},
        {"id": "loc", "name": "Library of Congress", "type": "metadata", "auth": "none"},
        {"id": "amazon", "name": "Amazon (via Google proxy)", "type": "metadata+covers", "auth": "none"},
        {"id": "viaf", "name": "VIAF (author authority)", "type": "author_disambiguation", "auth": "none"},
        {"id": "isni", "name": "ISNI (author IDs)", "type": "author_disambiguation", "auth": "none"},
        {"id": "inventaire", "name": "Inventaire (Wikidata-backed)", "type": "metadata", "auth": "none"},
        {"id": "bookbrainz", "name": "BookBrainz", "type": "metadata+identifiers", "auth": "none"},
    ]


# ── Calibre plugin sync endpoints ─────────────────────────────────────────
@app.get("/api/v1/calibre/pending")
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


@app.post("/api/v1/calibre/push")
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


@app.post("/api/v1/calibre/ack")
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
@app.get("/api/v1/catalog/check-owned")
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
    return {"owned": False}


# ── Library health report ─────────────────────────────────────────────────
@app.get("/api/v1/library/health")
async def library_health(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Comprehensive library health report."""
    total = await db.fetch_one("SELECT count(*) as n FROM books")
    n = total["n"] if total else 0
    no_cover = await db.fetch_one("SELECT count(*) as n FROM books WHERE cover_path IS NULL")
    no_isbn = await db.fetch_one("SELECT count(*) as n FROM books WHERE isbn IS NULL")
    no_desc = await db.fetch_one("SELECT count(*) as n FROM books WHERE description IS NULL OR description = ''")
    no_author = await db.fetch_one(
        "SELECT count(*) as n FROM books b WHERE NOT EXISTS (SELECT 1 FROM books_authors ba WHERE ba.book_id = b.id)"
    )
    dup_authors = await db.fetch_all("""
        SELECT lower(regexp_replace(name, '[^a-zA-Z ]', '', 'g')) as norm, array_agg(name) as names, count(*) as cnt
        FROM authors GROUP BY norm HAVING count(*) > 1 ORDER BY cnt DESC LIMIT 20
    """)
    series_gaps = await db.fetch_all("""
        SELECT s.name, array_agg(b.series_index ORDER BY b.series_index) as indices
        FROM books_series bs JOIN series s ON s.id = bs.series_id JOIN books b ON b.id = bs.book_id
        GROUP BY s.name HAVING count(*) > 1
    """)
    gaps = []
    for sg in series_gaps:
        indices = sorted([i for i in (sg["indices"] or []) if i])
        if indices and indices[-1] > len(indices):
            gaps.append({"series": sg["name"], "have": indices, "missing": [i for i in range(1, int(indices[-1]) + 1) if i not in indices]})

    return {
        "total_books": n,
        "missing_covers": {"count": no_cover["n"], "pct": round(no_cover["n"] / max(n, 1) * 100, 1)},
        "missing_isbn": {"count": no_isbn["n"], "pct": round(no_isbn["n"] / max(n, 1) * 100, 1)},
        "missing_description": {"count": no_desc["n"], "pct": round(no_desc["n"] / max(n, 1) * 100, 1)},
        "missing_author": {"count": no_author["n"], "pct": round(no_author["n"] / max(n, 1) * 100, 1)},
        "duplicate_authors": [{"names": d["names"], "count": d["cnt"]} for d in dup_authors],
        "series_gaps": gaps[:10],
    }


# ── "What should I read next" from own library ───────────────────────────
@app.get("/api/v1/recommendations/from-library")
async def recommend_from_library(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Recommend unread books from the user's own library, sorted by taste match."""
    from brainycat.taste import build_taste_profile, score_book

    profile = await build_taste_profile(str(user["id"]))
    rows = await db.fetch_all(
        """
        SELECT b.id, b.title, b.rating, b.quality_score, b.description, b.word_count,
               b.estimated_reading_minutes,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags,
               array_agg(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as series
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        LEFT JOIN books_series bs ON bs.book_id = b.id LEFT JOIN series s ON s.id = bs.series_id
        LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
        WHERE rp.id IS NULL
        GROUP BY b.id
    """,
        user["id"],
    )
    scored = []
    for r in rows:
        s = score_book(dict(r), profile)
        mins = r["estimated_reading_minutes"] or 0
        time_str = f"{mins // 60}h {mins % 60}m" if mins > 60 else f"{mins}m" if mins else ""
        scored.append(
            {
                "id": str(r["id"]),
                "title": r["title"],
                "authors": r["authors"] or [],
                "score": s,
                "reading_time": time_str,
                "quality": r["quality_score"],
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:20]


# ── Annotation export (Obsidian/Markdown) ─────────────────────────────────
@app.get("/api/v1/books/{book_id}/export/markdown")
async def export_markdown(book_id: str, user: Any = Depends(get_current_user)) -> Any:
    from uuid import UUID as _UUID

    from fastapi.responses import PlainTextResponse

    book = await db.fetch_one(
        """
        SELECT b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        _UUID(book_id),
    )
    if not book:
        return PlainTextResponse("Book not found")
    annotations = await db.fetch_all(
        """
        SELECT content, annotation_type, position, created_at FROM annotations
        WHERE book_id = $1 AND user_id = $2 ORDER BY created_at
    """,
        _UUID(book_id),
        user["id"],
    )
    progress = await db.fetch_one(
        "SELECT percentage, is_finished, updated_at FROM reading_progress WHERE book_id=$1 AND user_id=$2",
        _UUID(book_id),
        user["id"],
    )

    md = f"# {book['title']}\n**{', '.join(book['authors'] or [])}**\n\n"
    if progress:
        status = "Finished ✅" if progress["is_finished"] else f"{round((progress['percentage'] or 0) * 100)}% read"
        md += f"## Reading Status\n{status}\n\n"
    if annotations:
        highlights = [a for a in annotations if a["annotation_type"] == "highlight"]
        notes = [a for a in annotations if a["annotation_type"] == "note"]
        bookmarks = [a for a in annotations if "bookmark" in (a["annotation_type"] or "")]
        if highlights:
            md += "## Highlights\n" + "\n".join(f"> {h['content']}\n" for h in highlights) + "\n"
        if notes:
            md += "## Notes\n" + "\n".join(f"- {n['content']}\n" for n in notes) + "\n"
        if bookmarks:
            md += "## Bookmarks\n" + "\n".join(f"- 🔖 {b['content']}\n" for b in bookmarks) + "\n"
    md += "\n---\n*Exported from BrainyCat*\n"
    return PlainTextResponse(
        md, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{book["title"][:50]}.md"'}
    )


# ── OPDS import from external servers ─────────────────────────────────────
@app.get("/api/v1/catalog/opds-import")
async def opds_import_search(url: str = Query(""), q: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Search an external OPDS feed (calibre-server, Kavita, Komga, etc.)."""
    from xml.etree import ElementTree as ET

    import httpx

    if not url:
        return {"error": "provide OPDS feed URL"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
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


# ── Binary duplicate detection ────────────────────────────────────────────
@app.get("/api/v1/intelligence/exact-duplicates")
async def exact_duplicates(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.fingerprints import find_exact_duplicates

    return await find_exact_duplicates()


# ── Ingest pipeline ───────────────────────────────────────────────────────
@app.post("/api/v1/books/{book_id}/ingest")
async def run_ingest(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.ingest import ingest_book

    return await ingest_book(book_id)


@app.get("/api/v1/delivery/format")
async def delivery_format(
    device: str = Query("kindle"),
    book_id: str = Query(""),
    _u: Any = Depends(get_current_user),
) -> dict[str, str]:
    """Determine the best delivery format for a device."""
    from uuid import UUID as _UUID

    from brainycat.ingest import choose_delivery_format

    formats = []
    if book_id:
        rows = await db.fetch_all("SELECT format FROM book_files WHERE book_id = $1", _UUID(book_id))
        formats = [r["format"] for r in rows]
    book = await db.fetch_one("SELECT is_workbook FROM books WHERE id = $1", _UUID(book_id)) if book_id else None
    is_wb = (book["is_workbook"] if book else False) or False
    fmt = choose_delivery_format(device, formats, is_wb)
    return {"device": device, "format": fmt, "available": formats, "is_workbook": is_wb}
