"""Routes: media."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, Request

from brainycat import db, translation, tts
from brainycat.auth import get_current_user, require_admin

if TYPE_CHECKING:
    from brainycat.routes.models import MergeBody

router = APIRouter(prefix="/api/v1", tags=["media"])


@router.get("/tts/voices")
async def tts_voices() -> list[dict[str, str]]:
    return await tts.list_voices()


@router.get("/translation/backends")
async def translation_backends() -> list[dict[str, Any]]:
    return await translation.list_backends()


# ── Sync ─────────────────────────────────────────────────────────────────


@router.post("/epub-check/batch")
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


@router.post("/epub/merge")
async def epub_merge(body: MergeBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.epub_tools import merge_epubs

    return await merge_epubs(body.book_ids, body.title, body.author)


@router.get("/converters")
async def converters(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.format_convert import list_converters

    return await list_converters()


# ── DeACSM ───────────────────────────────────────────────────────────────


@router.get("/delivery/format")
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


# ── Smart PDF conversion ──────────────────────────────────────────────────


@router.get("/pdf-converters")
async def pdf_converters(_u: Any = Depends(get_current_user)) -> dict[str, bool]:
    from brainycat.pdf_convert import available_converters

    return available_converters()


# ── StoryGraph + Hardcover ────────────────────────────────────────────────


@router.get("/epub-styles")
async def list_epub_styles() -> list[dict[str, str]]:
    """List available EPUB default stylesheets."""
    return [
        {"id": "classic", "name": "Classic", "description": "Georgia serif, justified, book-style indents"},
        {"id": "modern", "name": "Modern", "description": "System sans-serif, left-aligned, clean"},
        {"id": "academic", "name": "Academic", "description": "Times New Roman, compact, reference-friendly"},
    ]


# ── Ambient quotes ────────────────────────────────────────────────────────


# ── TTS Podcast Feed ──────────────────────────────────────────────────────
@router.get("/podcast/{book_id}/feed.xml")
async def podcast_feed(book_id: str, request: Request) -> Any:
    """Serve TTS-generated audiobook chapters as a podcast RSS feed."""
    from uuid import UUID

    from fastapi.responses import Response

    book = await db.fetch_one("SELECT title, description FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return Response(content="<error>not found</error>", media_type="application/xml")

    # Find audio files for this book
    audio_files = await db.fetch_all(
        "SELECT file_path, file_name, format FROM book_files WHERE book_id = $1 AND format IN ('mp3', 'm4b', 'm4a', 'ogg') ORDER BY file_name",
        UUID(book_id),
    )

    base_url = str(request.base_url).rstrip("/")
    items = ""
    for i, af in enumerate(audio_files):
        items += f"""<item>
  <title>Chapter {i + 1} - {af["file_name"]}</title>
  <enclosure url="{base_url}/api/v1/books/{book_id}/file/{af["file_name"]}" type="audio/mpeg"/>
  <guid>{book_id}-ch{i}</guid>
</item>\n"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>{book["title"]}</title>
  <description>{(book["description"] or "")[:200]}</description>
  <link>{base_url}</link>
  {items}
</channel>
</rss>"""

    return Response(content=xml, media_type="application/rss+xml")
