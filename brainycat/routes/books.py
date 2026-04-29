"""Routes: books."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from brainycat import collections, convert, db, metadata, podcast, restoration, stats, stt, translation, tts
from brainycat.auth import get_current_user, require_admin
from brainycat.concurrency import heavy
from brainycat.http_client import get_client

if TYPE_CHECKING:
    from brainycat.routes.models import AuthorUpdate, BatchDeleteBody, BatchEnrichBody, BatchTagBody, BulkEnrichBody, BulkTagBody, NoteBody

router = APIRouter(prefix="/api/v1", tags=["books"])


@router.put("/books/{book_id}/author")
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
router.post("/collections")(collections.create_collection)
router.get("/collections")(collections.list_collections)
router.post("/collections/{collection_id}/books/{book_id}")(collections.add_book_to_collection)
router.delete("/collections/{collection_id}/books/{book_id}")(collections.remove_book_from_collection)
router.post("/books/{book_id}/link")(collections.link_books)


# ── Metadata enrichment ──────────────────────────────────────────────────


@router.post("/books/{book_id}/enrich")
async def enrich(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await metadata.enrich_book(book_id)


# ── Incoming scanner ─────────────────────────────────────────────────────


@router.post("/books/{book_id}/audio/diagnose")
async def audio_diagnose(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:

    f = await db.fetch_one("SELECT id FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac') LIMIT 1", UUID(book_id))
    if not f:
        return {"error": "No audio file"}
    return await restoration.diagnose(str(f["id"]))


@router.post("/books/{book_id}/audio/restore")
async def audio_restore(book_id: str, profile: str = Query("digital_light"), _u: Any = Depends(get_current_user)) -> dict[str, Any]:

    f = await db.fetch_one("SELECT id FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac') LIMIT 1", UUID(book_id))
    if not f:
        return {"error": "No audio file"}
    return await restoration.restore(str(f["id"]), profile)


@router.post("/books/{book_id}/audio/preview")
async def audio_preview(book_id: str, profile: str = Query("digital_light"), _u: Any = Depends(get_current_user)) -> Any:

    f = await db.fetch_one("SELECT id FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac') LIMIT 1", UUID(book_id))
    if not f:
        return {"error": "No audio file"}
    path = await restoration.preview(str(f["id"]), profile)
    if path:
        return FileResponse(path, media_type="audio/mpeg")
    return {"error": "Preview failed"}


# ── TTS / STT / Convert ─────────────────────────────────────────────────


@router.post("/books/{book_id}/convert/tts")
async def convert_tts(book_id: str, voice: str = Query("en_US-lessac-medium"), user: Any = Depends(get_current_user)) -> dict[str, str]:
    job_id = await tts.convert_to_audiobook(book_id, voice, str(user["id"]))
    return {"job_id": job_id}


@router.post("/books/{book_id}/convert/stt")
async def convert_stt(book_id: str, model: str = Query("small"), user: Any = Depends(get_current_user)) -> dict[str, str]:
    job_id = await stt.transcribe_audiobook(book_id, model, str(user["id"]))
    return {"job_id": job_id}


@router.post("/books/{book_id}/convert/{target_format}")
async def convert_format(book_id: str, target_format: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.conversion import convert_book

    return await convert_book(book_id, target_format)


@router.post("/books/{book_id}/send-to-kindle")
async def kindle(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await convert.send_to_kindle(book_id, str(user["id"]))


@router.post("/books/{book_id}/send-to-device")
async def device(book_id: str, email: str = Query(...), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await convert.send_to_device(book_id, email)


# ── Catalog (Gutenberg + LibriVox) ───────────────────────────────────────


# ── Translation ──────────────────────────────────────────────────────────


@router.post("/books/{book_id}/translate")
async def translate(
    book_id: str, target_lang: str = Query(...), backend: str = Query("argos"), user: Any = Depends(get_current_user)
) -> dict[str, str]:
    job_id = await translation.translate_book(book_id, target_lang, backend, str(user["id"]))
    return {"job_id": job_id}


@router.get("/books/{book_id}/notes")
async def get_note(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await stats.get_note(str(user["id"]), book_id) or {}


@router.post("/books/{book_id}/notes")
async def save_note(book_id: str, body: NoteBody, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await stats.save_note(str(user["id"]), book_id, body.content)


@router.post("/books/{book_id}/podcast-feed")
async def create_podcast(book_id: str, schedule: str = Query("daily"), user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await podcast.create_feed(book_id, str(user["id"]), schedule)


@router.post("/books/{book_id}/ocr")
async def ocr_book(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, str]:
    from brainycat.ocr import ocr_pdf

    job_id = await ocr_pdf(book_id, str(user["id"]))
    return {"job_id": job_id}


# ── Metadata download (Calibre-style) ───────────────────────────────────


@router.post("/books/{book_id}/download-metadata")
async def download_metadata(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await metadata.enrich_book(book_id)


@router.post("/books/{book_id}/download-cover")
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


@router.post("/books/{book_id}/classify")
async def classify_book(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.metadata import classify_genre_via_llm

    return await classify_genre_via_llm(book_id)


# ── PDF generation for Kindle ────────────────────────────────────────────


@router.post("/books/{book_id}/generate-pdf")
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


@router.post("/books/{book_id}/extract-isbn")
async def extract_book_isbn(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.isbn import extract_and_store_isbn

    return await extract_and_store_isbn(book_id)


# ── Enrichment stats ─────────────────────────────────────────────────────


@router.patch("/books/{book_id}/workbook")
async def toggle_workbook(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID as _UUID

    row = await db.fetch_one("SELECT is_workbook FROM books WHERE id = $1", _UUID(book_id))
    new_val = not (row["is_workbook"] if row else False)
    await db.execute("UPDATE books SET is_workbook = $1 WHERE id = $2", new_val, _UUID(book_id))
    return {"is_workbook": new_val}


# ── Metadata writeback ───────────────────────────────────────────────────


@router.post("/books/{book_id}/writeback")
async def writeback(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.writeback import writeback_metadata

    return await writeback_metadata(book_id)


@router.post("/writeback/batch")
async def batch_wb(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.writeback import batch_writeback

    return await batch_writeback(limit=50)


# ── Efficiency dashboard ─────────────────────────────────────────────────


@router.get("/books/{book_id}/bilingual")
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


@router.get("/books/{book_id}/similar")
async def similar_books(book_id: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.embeddings import find_similar

    return await find_similar(book_id)


# ── Real-time activity (WebSocket) ───────────────────────────────────────

_active_readers: dict[str, dict[str, Any]] = {}  # user_id → {book_id, title, percentage, updated}


@router.get("/books/{book_id}/shared-annotations")
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


@router.post("/books/{book_id}/index-content")
async def index_content(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.companion import index_book_content

    return await index_book_content(book_id)


@router.get("/books/{book_id}/search-content")
async def search_content(book_id: str, q: str = Query(...), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.companion import semantic_search

    return await semantic_search(book_id, q)


# ── Page/word count ──────────────────────────────────────────────────────


@router.post("/books/{book_id}/count-pages")
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


@router.post("/count-pages/batch")
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


@router.post("/bulk/tag")
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


@router.post("/bulk/enrich")
@heavy
async def bulk_enrich(body: BulkEnrichBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Trigger enrichment for multiple books."""
    enriched = 0
    for bid in body.book_ids:
        result = await metadata.enrich_book(bid)
        if result.get("enriched"):
            enriched += 1
    return {"enriched": enriched, "total": len(body.book_ids)}


# ── Batch operations (v1) ────────────────────────────────────────────────


@router.post("/books/batch/tag")
async def batch_tag(body: BatchTagBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add tags to multiple books."""
    from uuid import UUID as _UUID

    applied = 0
    for tag_name in body.tags:
        await db.execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", tag_name)
        tag_row = await db.fetch_one("SELECT id FROM tags WHERE name = $1", tag_name)
        if not tag_row:
            continue
        for bid in body.book_ids:
            await db.execute(
                "INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                _UUID(bid),
                tag_row["id"],
            )
            applied += 1
    return {"applied": applied}


@router.post("/books/batch/enrich")
@heavy
async def batch_enrich(body: BatchEnrichBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Trigger enrichment for multiple books."""
    enriched = 0
    for bid in body.book_ids:
        result = await metadata.enrich_book(bid)
        if result.get("enriched"):
            enriched += 1
    return {"enriched": enriched, "total": len(body.book_ids)}


@router.delete("/books/batch")
async def batch_delete(body: BatchDeleteBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Delete multiple books."""
    from uuid import UUID as _UUID

    from brainycat import storage

    deleted = 0
    for bid in body.book_ids:
        await db.execute("DELETE FROM books WHERE id = $1", _UUID(bid))
        storage.delete_book_dir(bid)
        deleted += 1
    return {"deleted": deleted}


# ── API Keys ─────────────────────────────────────────────────────────────


@router.post("/books/{book_id}/epub-check")
async def epub_check(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_check import check_epub

    return await check_epub(book_id)


@router.post("/books/{book_id}/epub-split")
async def epub_split(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_tools import split_epub

    return await split_epub(book_id)


# ── Embeddings reindex ───────────────────────────────────────────────────


@router.get("/books/{book_id}/sources")
async def book_sources(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.aggregator import aggregate_metadata

    return await aggregate_metadata(book_id)


@router.post("/books/{book_id}/epub-lint")
async def epub_lint(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_lint import lint_epub

    return await lint_epub(book_id)


# ── Goodreads import ─────────────────────────────────────────────────────


@router.post("/books/{book_id}/word-wise")
async def word_wise(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.worddumb import generate_word_wise

    return await generate_word_wise(book_id)


@router.post("/books/{book_id}/xray")
async def xray(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.worddumb import generate_xray

    return await generate_xray(book_id)


# ── AZW3 cover extraction ────────────────────────────────────────────────


@router.post("/books/{book_id}/extract-cover")
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


@router.post("/books/{book_id}/deacsm")
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


@router.post("/books/{book_id}/convert/kepub")
async def convert_kepub(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.kepub import epub_to_kepub

    return await epub_to_kepub(book_id)


# ── Cover settings ───────────────────────────────────────────────────────


@router.post("/books/{book_id}/custom/{column_name}")
async def set_custom_value(book_id: str, column_name: str, request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.custom_columns import set_value

    body = await request.json()
    return await set_value(book_id, column_name, body.get("value"))


# ── Virtual libraries ────────────────────────────────────────────────────


@router.post("/books/{book_id}/footnotes")
async def get_footnotes(book_id: str, request: Request, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.footnotes import generate_footnotes

    body = await request.json()
    return await generate_footnotes(book_id, body.get("text", ""), body.get("chapter_idx", 0))


# ── Adaptive chapter splitting ────────────────────────────────────────────


@router.post("/books/{book_id}/detect-chapters")
async def detect_chapters(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.chapter_split import detect_chapters as _detect

    return await _detect(book_id)


# ── Readability scoring ──────────────────────────────────────────────────


@router.post("/books/{book_id}/readability")
async def book_readability(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.readability import score_book_readability

    return await score_book_readability(book_id)


# ── Edition diffing ──────────────────────────────────────────────────────


@router.get("/books/{book_id}/summary")
async def book_summary_l1(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.summaries import summary_level1

    return await summary_level1(book_id)


@router.post("/books/{book_id}/summary")
async def book_summary_l2(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.summaries import summary_level2

    return await summary_level2(book_id)


@router.post("/books/{book_id}/goldmine")
async def book_goldmine(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.summaries import goldmine

    return await goldmine(book_id)


# ── Standard Ebooks catalog ──────────────────────────────────────────────


# ── GitHub ebook discovery ────────────────────────────────────────────────


# ── Open textbook sources ─────────────────────────────────────────────────


# ── Unified catalog search ────────────────────────────────────────────────


# ── Enhanced enrichment sources ───────────────────────────────────────────


@router.get("/books/{book_id}/export/markdown")
async def export_markdown(book_id: str, user: Any = Depends(get_current_user)) -> Any:
    from uuid import UUID as _UUID

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


# ── Binary duplicate detection ────────────────────────────────────────────


@router.post("/books/{book_id}/ingest")
async def run_ingest(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.ingest import ingest_book

    return await ingest_book(book_id)


@router.post("/books/{book_id}/pdf-to-epub")
async def smart_pdf_convert(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Convert PDF to EPUB3 using best available AI tool."""
    from brainycat.pdf_convert import pdf_to_epub3

    row = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1",
        __import__("uuid").UUID(book_id),
    )
    if not row:
        return {"error": "no PDF file"}
    result = await pdf_to_epub3(row["file_path"])
    if result.get("ok"):
        await db.execute(
            "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,'epub',$3,$4) ON CONFLICT DO NOTHING",
            __import__("uuid").uuid4(),
            __import__("uuid").UUID(book_id),
            result["path"],
            __import__("os").path.basename(result["path"]),
        )
    return result


@router.get("/books/{book_id}/reviews")
async def book_reviews_aggregated(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.reviews import aggregate_reviews

    book = await db.fetch_one(
        """
        SELECT b.title, b.isbn, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        __import__("uuid").UUID(book_id),
    )
    if not book:
        return {"error": "not found"}
    return await aggregate_reviews(book["title"], book["isbn"] or "", (book["authors"] or [""])[0])


# ── Additional catalog sources ────────────────────────────────────────────


# ── Serve file by format (for PDF read button) ───────────────────────────


@router.get("/books/{book_id}/file/by-format/{fmt}")
async def serve_file_by_format(book_id: str, fmt: str, _u: Any = Depends(get_current_user)) -> Any:
    """Serve a book file by format (epub, pdf, mobi, etc.)."""
    import os

    row = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = $2 LIMIT 1",
        __import__("uuid").UUID(book_id),
        fmt,
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"detail": "file not found"}
    mime = {"epub": "application/epub+zip", "pdf": "application/pdf", "mobi": "application/x-mobipocket-ebook"}.get(
        fmt, "application/octet-stream"
    )
    return FileResponse(row["file_path"], media_type=mime)


# ── Batch genre classification ────────────────────────────────────────────


@router.get("/series")
async def list_series(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    rows = await db.fetch_all("""
        SELECT s.id, s.name, count(bs.book_id) as book_count,
               array_agg(b.series_index ORDER BY b.series_index) FILTER (WHERE b.series_index IS NOT NULL) as indices
        FROM series s
        LEFT JOIN books_series bs ON bs.series_id = s.id
        LEFT JOIN books b ON b.id = bs.book_id
        GROUP BY s.id ORDER BY s.name
    """)
    result = []
    for r in rows:
        indices = sorted([i for i in (r["indices"] or []) if i])
        gaps = [i for i in range(1, int(max(indices, default=0)) + 1) if i not in indices] if indices else []
        result.append({"id": str(r["id"]), "name": r["name"], "book_count": r["book_count"], "indices": indices, "gaps": gaps})
    return result


@router.post("/series/{series_id}/reorder")
async def reorder_series(series_id: str, request: Request, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Reorder books in a series. Body: {"books": [{"book_id": "...", "index": 1}, ...]}"""
    body = await request.json()
    from uuid import UUID as _UUID

    for item in body.get("books", []):
        await db.execute("UPDATE books SET series_index = $1 WHERE id = $2", float(item["index"]), _UUID(item["book_id"]))
    return {"ok": True}


@router.post("/series/merge")
async def merge_series(request: Request, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Merge two series. Body: {"keep_id": "...", "merge_id": "..."}"""
    body = await request.json()
    from uuid import UUID as _UUID

    await db.execute("UPDATE books_series SET series_id = $1 WHERE series_id = $2", _UUID(body["keep_id"]), _UUID(body["merge_id"]))
    await db.execute("DELETE FROM series WHERE id = $1", _UUID(body["merge_id"]))
    return {"ok": True}


# ── EPUB Hyphenation ──────────────────────────────────────────────────────


@router.post("/books/{book_id}/hyphenate")
async def hyphenate_epub(book_id: str, language: str = Query("en"), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add CSS hyphenation to an EPUB for better justified text."""
    from uuid import UUID as _UUID

    row = await db.fetch_one("SELECT file_path FROM book_files WHERE book_id=$1 AND format='epub' LIMIT 1", _UUID(book_id))
    if not row:
        return {"error": "no epub"}
    import os
    import shutil
    import tempfile
    import zipfile

    src = row["file_path"]
    tmp = tempfile.mktemp(suffix=".epub")
    hyphen_css = f"""
    body {{ -webkit-hyphens: auto; -moz-hyphens: auto; hyphens: auto; }}
    p {{ -webkit-hyphens: auto; hyphens: auto; }}
    html {{ -webkit-locale: "{language}"; }}
    """
    try:
        with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith((".xhtml", ".html", ".htm")):
                    text = data.decode("utf-8", errors="replace")
                    if "</head>" in text:
                        text = text.replace("</head>", f"<style>{hyphen_css}</style></head>")
                    data = text.encode("utf-8")
                zout.writestr(item, data)
        shutil.move(tmp, src)
        return {"ok": True, "language": language}
    except Exception as e:
        if os.path.isfile(tmp):
            os.unlink(tmp)
        return {"error": str(e)[:100]}


# ── Regional metadata sources ─────────────────────────────────────────────


@router.post("/books/{book_id}/ocr-to-epub")
async def ocr_to_epub(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Full pipeline: scanned PDF → OCR via Intello → EPUB3."""
    from uuid import UUID as _UUID

    # Step 1: Find the PDF
    row = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE book_id=$1 AND format='pdf' LIMIT 1",
        _UUID(book_id),
    )
    if not row:
        return {"error": "no PDF file"}

    # Step 2: Submit OCR job to Intello
    from brainycat.async_jobs import submit_job

    with open(row["file_path"], "rb") as fh:
        result = await submit_job(book_id, "ocr", "/api/v1/ocr/jobs", files={"file": fh})
    if not result.get("ok"):
        return {"error": "OCR submission failed", "detail": result}

    # Step 3: The OCR result will be a searchable PDF — convert to EPUB
    # This happens asynchronously. The job status can be polled.
    return {
        "ok": True,
        "job_id": result.get("job_id"),
        "status": "submitted",
        "next_steps": [
            f"Poll: GET /api/v1/jobs?book_id={book_id}",
            f"When complete: POST /api/v1/books/{book_id}/pdf-to-epub",
            f"Compare: GET /api/v1/books/{book_id}/compare",
        ],
    }


# ── Side-by-side comparison (PDF vs EPUB) ─────────────────────────────────


@router.get("/books/{book_id}/compare")
async def compare_formats(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Compare PDF and EPUB versions of a book for human review."""
    from uuid import UUID as _UUID

    files = await db.fetch_all(
        "SELECT id, format, file_path, file_name FROM book_files WHERE book_id=$1",
        _UUID(book_id),
    )
    pdf = next((f for f in files if f["format"] == "pdf"), None)
    epub = next((f for f in files if f["format"] == "epub"), None)

    if not pdf or not epub:
        return {"error": "need both PDF and EPUB to compare", "formats": [f["format"] for f in files]}

    # Extract text samples from both
    pdf_text = ""
    try:
        import fitz

        doc = fitz.open(pdf["file_path"])
        for page in doc[:3]:  # First 3 pages
            pdf_text += page.get_text() + "\n---PAGE---\n"
        doc.close()
    except Exception:
        pdf_text = "(could not extract PDF text)"

    epub_text = ""
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(epub["file_path"], options={"ignore_ncx": True})
        for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):
            if i >= 3:
                break
            soup = BeautifulSoup(item.get_content(), "html.parser")
            epub_text += soup.get_text(separator="\n", strip=True) + "\n---CHAPTER---\n"
    except Exception:
        epub_text = "(could not extract EPUB text)"

    return {
        "book_id": book_id,
        "pdf": {"file_id": str(pdf["id"]), "file_name": pdf["file_name"], "text_sample": pdf_text[:3000]},
        "epub": {"file_id": str(epub["id"]), "file_name": epub["file_name"], "text_sample": epub_text[:3000]},
        "view_urls": {
            "pdf": f"/api/v1/books/{book_id}/file/{pdf['id']}",
            "epub_reader": f"/static/reader.html?id={book_id}",
        },
    }


# ── Scraper diagnostics — human-in-the-loop ───────────────────────────────


@router.get("/books/{book_id}/isbn-region")
async def book_isbn_region(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.isbn import isbn_to_region

    book = await db.fetch_one("SELECT isbn, title FROM books WHERE id = $1", __import__("uuid").UUID(book_id))
    if not book or not book["isbn"]:
        return {"error": "no ISBN"}
    region = isbn_to_region(book["isbn"])
    return {"isbn": book["isbn"], "title": book["title"], "region": region}


@router.get("/books/{book_id}/editions")
async def book_editions(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Find other editions of the same book using Open Library Work ID."""
    book = await db.fetch_one(
        "SELECT title, isbn, extra_metadata FROM books WHERE id = $1",
        __import__("uuid").UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    import json as _j

    em = book["extra_metadata"]
    if isinstance(em, str):
        try:
            em = _j.loads(em)
        except Exception:
            em = {}
    work_id = (em or {}).get("ol_work_id")
    if not work_id:
        return {"error": "no Work ID — run resolve-work-ids first", "isbn": book["isbn"]}

    # Check library for same Work ID
    owned = await db.fetch_all(
        """
        SELECT id, title, isbn, extra_metadata->>'ol_work_id' as work_id
        FROM books WHERE extra_metadata->>'ol_work_id' = $1 AND id != $2
    """,
        work_id,
        __import__("uuid").UUID(book_id),
    )

    # Fetch all editions from Open Library
    editions = []
    try:
        c = get_client()
        resp = await c.get(f"https://openlibrary.org/works/{work_id}/editions.json?limit=20")
        if resp.status_code == 200:
            for ed in resp.json().get("entries", []):
                editions.append(
                    {
                        "title": ed.get("title"),
                        "isbn": (ed.get("isbn_13") or ed.get("isbn_10") or [None])[0],
                        "publisher": (ed.get("publishers") or [None])[0],
                        "publish_date": ed.get("publish_date"),
                        "language": (ed.get("languages") or [{}])[0].get("key", "").replace("/languages/", ""),
                    }
                )
    except Exception:
        pass

    return {
        "work_id": work_id,
        "title": book["title"],
        "owned_editions": [{"id": str(o["id"]), "title": o["title"], "isbn": o["isbn"]} for o in owned],
        "all_editions": editions,
        "you_own": len(owned) + 1,
        "total_editions": len(editions),
    }


# ── ISBN intelligence (publisher + region + best sources) ─────────────────


@router.get("/works")
async def list_works(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Group books by Open Library Work ID — FRBR Work-level view."""
    rows = await db.fetch_all("""
        SELECT extra_metadata->>'ol_work_id' as work_id,
               array_agg(DISTINCT b.title) as titles,
               array_agg(DISTINCT b.isbn) FILTER (WHERE b.isbn IS NOT NULL) as isbns,
               array_agg(DISTINCT b.id) as book_ids,
               count(*) as edition_count
        FROM books b
        WHERE extra_metadata->>'ol_work_id' IS NOT NULL
        GROUP BY extra_metadata->>'ol_work_id'
        HAVING count(*) > 1
        ORDER BY count(*) DESC
    """)
    return [
        {
            "work_id": r["work_id"],
            "titles": r["titles"],
            "isbns": r["isbns"],
            "edition_count": r["edition_count"],
            "book_ids": [str(i) for i in r["book_ids"]],
        }
        for r in rows
    ]


# ── Deterministic ISBN route (bypass search entirely) ─────────────────────


@router.post("/books/{book_id}/extract-identifiers")
async def extract_identifiers(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Extract national identifiers (ARK, NBN, DOI, LCCN) from book content."""
    import re
    from uuid import UUID as _UUID

    row = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE book_id=$1 AND format='epub' LIMIT 1",
        _UUID(book_id),
    )
    if not row:
        return {"error": "no epub"}

    # Extract text from first/last pages (where identifiers live)
    text = ""
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        for item in items[:3] + items[-3:]:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text(separator=" ", strip=True) + "\n"
    except Exception:
        return {"error": "could not read epub"}

    identifiers: dict[str, str] = {}

    # BnF ARK
    ark = re.search(r"ark:/12148/(\w+)", text)
    if ark:
        identifiers["bnf_ark"] = f"ark:/12148/{ark.group(1)}"

    # DOI
    doi = re.search(r"(10\.\d{4,}/[^\s]+)", text)
    if doi:
        identifiers["doi"] = doi.group(1).rstrip(".")

    # LCCN
    lccn = re.search(r"LCCN[:\s]+(\d{8,10})", text, re.IGNORECASE)
    if lccn:
        identifiers["lccn"] = lccn.group(1)

    # Dépôt légal
    depot = re.search(r"[Dd]épôt\s+légal\s*[:\s]+(.{5,30})", text)
    if depot:
        identifiers["depot_legal"] = depot.group(1).strip()

    # Store found identifiers
    if identifiers:
        import json

        await db.execute(
            "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
            json.dumps({"identifiers": identifiers}),
            _UUID(book_id),
        )

    return {"identifiers": identifiers, "scanned_chars": len(text)}


# ── Cover regeneration ────────────────────────────────────────────────────


@router.post("/books/{book_id}/generate-cover")
async def regenerate_cover(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Regenerate cover from current title/author (after title cleanup)."""
    from uuid import UUID as _UUID

    from brainycat.atomic import atomic_write
    from brainycat.covers import generate_cover

    book = await db.fetch_one(
        """
        SELECT b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        _UUID(book_id),
    )
    if not book:
        return {"error": "not found"}
    cover_data = generate_cover(book["title"], ", ".join(book["authors"] or []))
    if not cover_data:
        return {"error": "cover generation failed"}
    import os

    from brainycat.storage import book_dir

    cover_path = os.path.join(book_dir(book_id), "cover.jpg")
    os.makedirs(os.path.dirname(cover_path), exist_ok=True)
    with atomic_write(cover_path) as f:
        f.write(cover_data)
    await db.execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, _UUID(book_id))
    return {"ok": True, "path": cover_path, "size": len(cover_data)}


# ── Last-page OCR for ISBN ────────────────────────────────────────────────


@router.post("/books/{book_id}/ocr-isbn")
async def ocr_isbn(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """OCR just the last page of a scanned PDF to find the ISBN barcode."""
    from brainycat.isbn import ocr_last_page_for_isbn

    return await ocr_last_page_for_isbn(book_id)


@router.post("/books/{book_id}/convert/epub")
async def convert_to_epub(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Convert a non-EPUB book file to EPUB for the reader."""
    import os
    from uuid import UUID as _UUID

    from brainycat.conversion import convert
    from brainycat.storage import book_dir

    row = await db.fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf "
        "WHERE bf.book_id = $1 AND bf.format != 'epub' "
        "ORDER BY CASE bf.format WHEN 'mobi' THEN 1 WHEN 'azw3' THEN 2 WHEN 'pdf' THEN 3 ELSE 4 END LIMIT 1",
        _UUID(book_id),
    )
    if not row:
        return {"error": "no convertible file"}
    out_path = os.path.join(book_dir(book_id), "converted.epub")
    result = await convert(row["file_path"], out_path, "epub")
    if not result.get("ok"):
        return {"error": result.get("error", "conversion failed")}
    file_id = await db.fetch_val(
        "INSERT INTO book_files (book_id, file_path, format, file_size) VALUES ($1, $2, 'epub', $3) RETURNING id",
        _UUID(book_id),
        out_path,
        os.path.getsize(out_path),
    )
    return {"ok": True, "file_id": str(file_id)}


# ── Audiobook chapter merge + retag ───────────────────────────────────────


@router.post("/books/{book_id}/audio/merge-chapters")
async def merge_audio_chapters(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Merge multiple MP3 chapter files into a single M4B with chapter markers."""
    import asyncio as _aio

    from brainycat.storage import book_dir

    files = await db.fetch_all(
        "SELECT id, file_path, file_size FROM book_files WHERE book_id = $1 AND format = 'mp3' ORDER BY file_path",
        UUID(book_id),
    )
    if len(files) < 2:
        return {"error": "need 2+ MP3 files to merge"}

    book = await db.fetch_one(
        "SELECT b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors "
        "FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id "
        "WHERE b.id = $1 GROUP BY b.id",
        UUID(book_id),
    )
    title = book["title"] or "Unknown"
    author = ", ".join(book["authors"] or ["Unknown"])

    bdir = book_dir(book_id)
    concat_list = os.path.join(bdir, "concat.txt")
    m4b_path = os.path.join(bdir, f"{title[:50]}.m4b")

    # Build ffmpeg concat list and extract chapter info
    chapters = []
    offset = 0.0
    with open(concat_list, "w") as f:
        for fi in files:
            f.write(f"file '{fi['file_path'].replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
            # Get duration
            probe = await _aio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                fi["file_path"],
                stdout=_aio.subprocess.PIPE,
                stderr=_aio.subprocess.PIPE,
            )
            out, _ = await probe.communicate()
            dur = float(out.decode().strip() or "0")
            ch_title = os.path.splitext(os.path.basename(fi["file_path"]))[0]
            chapters.append({"title": ch_title, "start": offset})
            offset += dur

    # Build chapter metadata file
    meta_path = os.path.join(bdir, "chapters.txt")
    with open(meta_path, "w") as f:
        f.write(";FFMETADATA1\n")
        f.write(f"title={title}\n")
        f.write(f"artist={author}\n")
        f.write(f"album={title}\n")
        f.write("genre=Audiobook\n")
        for i, ch in enumerate(chapters):
            end = chapters[i + 1]["start"] if i + 1 < len(chapters) else offset
            f.write("\n[CHAPTER]\nTIMEBASE=1/1000\n")
            f.write(f"START={int(ch['start'] * 1000)}\n")
            f.write(f"END={int(end * 1000)}\n")
            f.write(f"title={ch['title']}\n")

    # Merge: concat MP3s → re-encode to AAC 64k mono (speech quality) → M4B
    proc = await _aio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list,
        "-i",
        meta_path,
        "-map_metadata",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ac",
        "1",
        "-ar",
        "22050",
        "-movflags",
        "+faststart",
        m4b_path,
        stdout=_aio.subprocess.PIPE,
        stderr=_aio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    for _tmp in (concat_list, meta_path):
        if os.path.exists(_tmp):
            os.unlink(_tmp)

    if proc.returncode != 0:
        return {"error": f"ffmpeg failed: {err.decode()[-200:]}"}

    size = os.path.getsize(m4b_path)
    file_id = await db.fetch_val(
        "INSERT INTO book_files (book_id, file_path, format, file_size) VALUES ($1, $2, 'm4b', $3) RETURNING id",
        UUID(book_id),
        m4b_path,
        size,
    )
    await db.execute(
        "UPDATE books SET duration_seconds = $1, narrator = COALESCE(narrator, $2) WHERE id = $3",
        int(offset),
        author,
        UUID(book_id),
    )
    return {
        "ok": True,
        "file_id": str(file_id),
        "chapters": len(chapters),
        "duration_seconds": int(offset),
        "size_mb": round(size / 1048576, 1),
    }


# ── User settings (Kindle email, preferences) ────────────────────────────


@router.post("/books/{book_id}/clippings")
async def save_clipping(book_id: str, body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from uuid import UUID as _UUID

    await db.execute(
        "INSERT INTO clippings (user_id, book_id, text, cfi, created_at) VALUES ($1, $2, $3, $4, now())",
        user["id"],
        _UUID(book_id),
        body.get("text", "")[:2000],
        body.get("cfi"),
    )
    return {"ok": True}


@router.get("/books/{book_id}/clippings")
async def get_clippings(book_id: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from uuid import UUID as _UUID

    rows = await db.fetch_all(
        "SELECT text, cfi, created_at FROM clippings WHERE user_id = $1 AND book_id = $2 ORDER BY created_at DESC",
        user["id"],
        _UUID(book_id),
    )
    return [dict(r) for r in rows]


# ── AI explain / translate (via Intello, graceful fallback) ───────────────


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


@router.delete("/books/{book_id}/file/{file_id}")
async def delete_book_file(book_id: str, file_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Delete a specific file version from a book (keep at least one)."""
    remaining = await db.fetch_one(
        "SELECT count(*) as cnt FROM book_files WHERE book_id = $1",
        UUID(book_id),
    )
    if remaining["cnt"] <= 1:
        return {"error": "Cannot delete the only file"}
    row = await db.fetch_one(
        "SELECT file_path FROM book_files WHERE id = $1 AND book_id = $2",
        UUID(file_id),
        UUID(book_id),
    )
    if not row:
        return {"error": "File not found"}
    if row["file_path"] and os.path.exists(row["file_path"]):
        os.unlink(row["file_path"])
    await db.execute("DELETE FROM book_files WHERE id = $1", UUID(file_id))
    return {"ok": True}


@router.get("/search/fulltext")
async def fulltext_search(q: str = Query(...), limit: int = Query(20), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Full-text search across all books — titles, authors, descriptions, ISBN."""
    from brainycat.db import fetch_all as _fa

    rows = await _fa(
        """
        SELECT b.id, b.title, b.isbn, b.quality_score, b.cover_path,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               ts_rank(b.search_vector, websearch_to_tsquery('simple', $1)) as rank
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id
        LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.search_vector @@ websearch_to_tsquery('simple', $1)
           OR b.title ILIKE '%' || $1 || '%'
           OR b.isbn = $1
           OR EXISTS (SELECT 1 FROM authors a2 JOIN books_authors ba2 ON ba2.author_id = a2.id WHERE ba2.book_id = b.id AND a2.name ILIKE '%' || $1 || '%')
        GROUP BY b.id
        ORDER BY rank DESC NULLS LAST, b.quality_score DESC
        LIMIT $2
    """,
        q,
        limit,
    )

    return {"query": q, "results": [dict(r) for r in rows], "count": len(rows)}


@router.get("/books/{book_id}/pdf-page/{page_num}")
async def serve_pdf_page(book_id: str, page_num: int, _u: Any = Depends(get_current_user)) -> Any:
    """Serve a single PDF page as PNG — for range-streaming large PDFs."""
    import fitz
    from fastapi.responses import Response

    row = await db.fetch_one(
        "SELECT bf.file_path FROM book_files bf WHERE bf.book_id = $1 AND bf.format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"error": "not found"}

    doc = fitz.open(row["file_path"])
    if page_num < 0 or page_num >= len(doc):
        doc.close()
        return {"error": "page out of range"}

    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    doc.close()

    return Response(content=img_bytes, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
