"""Metadata extraction from ebook and audio files."""

from __future__ import annotations

import os
from typing import Any


def extract_metadata(file_path: str) -> dict[str, Any]:
    """Extract metadata from a file based on its extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".epub":
        return _extract_epub(file_path)
    if ext == ".pdf":
        return _extract_pdf(file_path)
    if ext in {".mp3", ".m4b", ".m4a", ".flac", ".ogg", ".opus"}:
        return _extract_audio(file_path)
    return {"format": ext.lstrip(".")}


def _extract_epub(path: str) -> dict[str, Any]:
    try:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(path, options={"ignore_ncx": True})
        title = book.get_metadata("DC", "title")
        author = book.get_metadata("DC", "creator")
        lang = book.get_metadata("DC", "language")
        desc = book.get_metadata("DC", "description")
        isbn_meta = book.get_metadata("DC", "identifier")

        cover_data = None
        for item in book.get_items_of_type(ebooklib.ITEM_COVER):
            cover_data = item.get_content()
            break
        if not cover_data:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if "cover" in (item.get_name() or "").lower():
                    cover_data = item.get_content()
                    break

        return {
            "format": "epub",
            "title": title[0][0] if title else None,
            "author": author[0][0] if author else None,
            "language": lang[0][0] if lang else None,
            "description": desc[0][0] if desc else None,
            "isbn": isbn_meta[0][0] if isbn_meta else None,
            "cover_data": cover_data,
        }
    except Exception:
        return {"format": "epub"}


def _extract_pdf(path: str) -> dict[str, Any]:
    try:
        import fitz

        doc = fitz.open(path)
        meta = doc.metadata or {}
        return {
            "format": "pdf",
            "title": meta.get("title") or None,
            "author": meta.get("author") or None,
            "description": meta.get("subject") or None,
        }
    except Exception:
        return {"format": "pdf"}


def _extract_audio(path: str) -> dict[str, Any]:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path, easy=True)
        if audio is None:
            return {"format": os.path.splitext(path)[1].lstrip(".")}

        info = audio.info
        tags = dict(audio.tags) if audio.tags else {}
        title = tags.get("title", [None])[0]
        artist = tags.get("artist", [None])[0]
        album = tags.get("album", [None])[0]

        # Chapter detection for M4B
        chapters: list[dict[str, Any]] = []
        try:
            from mutagen.mp4 import MP4

            raw = MP4(path)
            if hasattr(raw, "chapters") and raw.chapters:
                for i, ch in enumerate(raw.chapters):
                    chapters.append({"index": i, "title": ch.title, "start": ch.start})
        except Exception:
            pass

        return {
            "format": os.path.splitext(path)[1].lstrip("."),
            "title": title or album,
            "author": artist,
            "duration_seconds": info.length if info else None,
            "bitrate": getattr(info, "bitrate", None),
            "has_chapters": len(chapters) > 0,
            "chapters": chapters,
        }
    except Exception:
        return {"format": os.path.splitext(path)[1].lstrip(".")}
