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
    if ext == ".mobi":
        return _extract_mobi(file_path)
    return {"format": ext.lstrip(".")}


def _extract_mobi(path: str) -> dict[str, Any]:
    """Extract metadata from MOBI files by parsing the binary header."""
    try:
        with open(path, "rb") as f:
            data = f.read(500)

        # MOBI header: PalmDB format
        # Title is at offset 0, null-terminated, up to 32 bytes
        title = data[:32].split(b"\x00")[0].decode(errors="replace").strip()

        # Look for EXTH header which contains metadata
        exth_pos = data.find(b"EXTH")
        result: dict[str, Any] = {"format": "mobi", "title": title or None}

        if exth_pos > 0:
            # Read full EXTH for metadata
            with open(path, "rb") as f:
                full = f.read(min(os.path.getsize(path), 100000))

            exth_pos = full.find(b"EXTH")
            if exth_pos > 0:
                # EXTH records: type(4) + length(4) + data
                pos = exth_pos + 12  # skip header
                num_records = int.from_bytes(full[exth_pos + 8 : exth_pos + 12], "big")
                for _ in range(min(num_records, 50)):
                    if pos + 8 > len(full):
                        break
                    rec_type = int.from_bytes(full[pos : pos + 4], "big")
                    rec_len = int.from_bytes(full[pos + 4 : pos + 8], "big")
                    if rec_len < 8 or pos + rec_len > len(full):
                        break
                    rec_data = full[pos + 8 : pos + rec_len].decode(errors="replace").strip()
                    if rec_type == 100:
                        result["author"] = rec_data
                    elif rec_type == 101:
                        result["publisher"] = rec_data
                    elif rec_type == 103:
                        result["description"] = rec_data
                    elif rec_type == 104:
                        result["isbn"] = rec_data
                    elif rec_type == 105:
                        result["genre"] = rec_data
                    elif rec_type == 503:
                        result["title"] = rec_data  # updated title
                    pos += rec_len

        return result
    except Exception:
        return {"format": "mobi"}


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

        # Extract cover from first page
        cover_data = None
        if len(doc) > 0:
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            if pix.width > 600:
                scale = 600 / pix.width
                pix = page.get_pixmap(matrix=fitz.Matrix(scale * 1.5, scale * 1.5))
            cover_data = pix.tobytes("jpeg")

        doc.close()
        return {
            "format": "pdf",
            "title": meta.get("title") or None,
            "author": meta.get("author") or None,
            "description": meta.get("subject") or None,
            "cover_data": cover_data,
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
