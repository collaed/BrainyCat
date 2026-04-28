"""Book CRUD service and route handlers."""

from __future__ import annotations

import mimetypes
import os
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from brainycat import storage
from brainycat.auth import get_current_user, require_admin
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.extract import extract_metadata

ALLOWED_FORMATS = {".epub", ".pdf", ".mobi", ".mp3", ".m4b", ".m4a", ".opus", ".flac", ".ogg"}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def upload_book(
    file: UploadFile,
    user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """POST /api/v1/books/upload — upload a book file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

    # Stream to disk (not into memory) to handle large audiobooks
    book_id = str(uuid4())
    file_path = storage.upload_path(book_id, file.filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    size = 0
    with open(file_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            out.write(chunk)
            size += len(chunk)

    # If zip, extract and process each file inside
    if ext == ".zip":
        import zipfile

        results = []
        with zipfile.ZipFile(file_path) as zf:
            for name in zf.namelist():
                inner_ext = os.path.splitext(name)[1].lower()
                if inner_ext in ALLOWED_FORMATS and inner_ext != ".zip":
                    inner_path = os.path.join(storage.book_dir(book_id), os.path.basename(name))
                    with zf.open(name) as src, open(inner_path, "wb") as dst:
                        import shutil

                        shutil.copyfileobj(src, dst)
                    results.append(os.path.basename(name))
            if not results:
                return {"error": "No supported files in zip"}
            # Use the first extracted file as the main book
            file_path = os.path.join(storage.book_dir(book_id), results[0])
            ext = os.path.splitext(results[0])[1].lower()
        os.unlink(os.path.join(storage.book_dir(book_id), os.path.basename(file.filename)))

    # Save original filename
    original_filename = file.filename

    # Extract metadata
    meta = extract_metadata(file_path)
    title = meta.get("title") or os.path.splitext(file.filename)[0]
    author_name = meta.get("author")

    # Save cover if present
    cover_path = None
    cover_data = meta.get("cover_data")
    if cover_data:
        cover_path = os.path.join(storage.book_dir(book_id), "cover.jpg")
        with open(cover_path, "wb") as f:
            f.write(cover_data)

    # Duplicate check
    dup = await fetch_one(
        "SELECT id, title FROM books WHERE title = $1 OR (isbn IS NOT NULL AND isbn = $2)",
        title,
        meta.get("isbn"),
    )
    if dup:
        return {
            "warning": "duplicate",
            "existing_id": str(dup["id"]),
            "existing_title": dup["title"],
            "book_id": book_id,
        }

    # Insert book
    await execute(
        """INSERT INTO books (id, title, original_filename, isbn, description, cover_path, pubdate)
           VALUES ($1, $2, $3, $3, $4, $5, $6)""",
        UUID(book_id),
        title,
        meta.get("isbn"),
        meta.get("description"),
        cover_path,
        None,
    )

    # Insert book file
    mime = mimetypes.guess_type(file.filename)[0]
    await execute(
        """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size, mime_type, bitrate, duration_seconds, has_chapters)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
        uuid4(),
        UUID(book_id),
        meta.get("format", ext.lstrip(".")),
        file_path,
        file.filename,
        size,
        mime,
        meta.get("bitrate"),
        meta.get("duration_seconds"),
        meta.get("has_chapters", False),
    )

    # Clean author name — filter garbage
    if author_name:
        garbage = {"libgen.li", "libgen", "z-lib", "unknown", "n/a", "user", "admin", "calibre", "anonymous"}
        if author_name.lower().strip() in garbage or "/" in author_name or len(author_name) > 100:
            author_name = None

    # Insert author if present
    if author_name:
        await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", author_name)
        author_row = await fetch_one("SELECT id FROM authors WHERE name = $1", author_name)
        if author_row:
            await execute(
                "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                UUID(book_id),
                author_row["id"],
            )

    # Insert language if present
    lang = meta.get("language")
    if lang:
        await execute("INSERT INTO languages (code) VALUES ($1) ON CONFLICT (code) DO NOTHING", lang)
        lang_row = await fetch_one("SELECT id FROM languages WHERE code = $1", lang)
        if lang_row:
            await execute(
                "INSERT INTO books_languages (book_id, language_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                UUID(book_id),
                lang_row["id"],
            )

    # Insert audio chapters
    for ch in meta.get("chapters", []):
        await execute(
            """INSERT INTO audio_chapters (file_id, chapter_index, title, start_time, end_time)
               VALUES ((SELECT id FROM book_files WHERE book_id = $1 LIMIT 1), $2, $3, $4, $5)""",
            UUID(book_id),
            ch["index"],
            ch.get("title"),
            ch.get("start", 0),
            ch.get("start", 0),  # end_time updated later
        )

    return {"book_id": book_id, "title": title, "author": author_name, "format": meta.get("format")}


# ---------------------------------------------------------------------------
# List / Search
# ---------------------------------------------------------------------------


async def list_books(
    q: str | None = Query(None),
    book_format: str | None = Query(None, alias="format"),
    language: str | None = Query(None),
    tag: str | None = Query(None),
    author: str | None = Query(None),
    missing: str | None = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50, le=2000),
    offset: int = Query(0),
    _user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """GET /api/v1/books — list with filtering and search."""
    conditions = []
    params: list[Any] = []
    idx = 1

    if q:
        # Quoted phrases use phraseto_tsquery for exact phrase matching
        if '"' in q:
            clean_q = q.replace('"', "")
            ts_fn = "phraseto_tsquery"
        else:
            clean_q = q
            ts_fn = "plainto_tsquery"
        conditions.append(
            f"(b.title ILIKE '%' || ${idx} || '%' OR EXISTS (SELECT 1 FROM books_authors ba2 JOIN authors a2 ON a2.id = ba2.author_id WHERE ba2.book_id = b.id AND a2.name ILIKE '%' || ${idx} || '%') OR b.search_vector @@ {ts_fn}('simple', unaccent(${idx})) OR similarity(b.title, ${idx}) > 0.3)"
        )
        params.append(clean_q)
        idx += 1

    if missing:
        if missing == "no_isbn":
            conditions.append("b.isbn IS NULL")
        elif missing == "no_desc":
            conditions.append("(b.description IS NULL OR b.description = '')")
        elif missing == "no_cover":
            conditions.append("b.cover_path IS NULL")
        elif missing == "no_tags":
            conditions.append("NOT EXISTS (SELECT 1 FROM books_tags bt WHERE bt.book_id = b.id)")
        elif missing == "low_quality":
            conditions.append("(b.quality_score IS NULL OR b.quality_score < 30)")

    if book_format:
        conditions.append(f"EXISTS (SELECT 1 FROM book_files bf WHERE bf.book_id = b.id AND bf.format = ${idx})")
        params.append(book_format)
        idx += 1

    if language:
        conditions.append(
            f"EXISTS (SELECT 1 FROM books_languages bl JOIN languages l ON l.id = bl.language_id WHERE bl.book_id = b.id AND l.code = ${idx})"
        )
        params.append(language)
        idx += 1

    if tag:
        conditions.append(
            f"EXISTS (SELECT 1 FROM books_tags bt JOIN tags t ON t.id = bt.tag_id WHERE bt.book_id = b.id AND t.name = ${idx})"
        )
        params.append(tag)
        idx += 1

    if author:
        conditions.append(
            f"EXISTS (SELECT 1 FROM books_authors ba JOIN authors a ON a.id = ba.author_id WHERE ba.book_id = b.id AND similarity(a.name, ${idx}) > 0.3)"
        )
        params.append(author)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    allowed_sorts = {
        "title": "b.sort_title",
        "updated_at": "b.updated_at",
        "created_at": "b.created_at",
        "quality_score": "b.quality_score",
    }
    sort_col = allowed_sorts.get(sort, "b.updated_at")
    order_dir = "ASC" if order.lower() == "asc" else "DESC"

    count_row = await fetch_one(f"SELECT count(*) as total FROM books b {where}", *params)
    total = count_row["total"] if count_row else 0

    params.extend([limit, offset])
    rows = await fetch_all(
        f"""SELECT b.*, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
                   array_agg(DISTINCT bf.format) FILTER (WHERE bf.format IS NOT NULL) as formats
            FROM books b
            LEFT JOIN books_authors ba ON ba.book_id = b.id
            LEFT JOIN authors a ON a.id = ba.author_id
            LEFT JOIN book_files bf ON bf.book_id = b.id
            {where}
            GROUP BY b.id
            ORDER BY {sort_col} {order_dir}
            LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )

    return {
        "total": total,
        "books": [_book_dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Single book
# ---------------------------------------------------------------------------


async def get_book(book_id: str, _user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """GET /api/v1/books/{book_id}"""
    row = await fetch_one(
        """SELECT b.*, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
                  array_agg(DISTINCT bf.format) FILTER (WHERE bf.format IS NOT NULL) as formats
           FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           LEFT JOIN book_files bf ON bf.book_id = b.id
           WHERE b.id = $1 GROUP BY b.id""",
        UUID(book_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Book not found")

    files = await fetch_all("SELECT * FROM book_files WHERE book_id = $1", UUID(book_id))
    links = await fetch_all(
        """SELECT bl.*, b.title as linked_title FROM book_links bl
           JOIN books b ON b.id = CASE WHEN bl.book_a_id = $1 THEN bl.book_b_id ELSE bl.book_a_id END
           WHERE bl.book_a_id = $1 OR bl.book_b_id = $1""",
        UUID(book_id),
    )

    return {
        **_book_dict(row),
        "files": [dict(f) for f in files],
        "links": [dict(lnk) for lnk in links],
    }


async def update_book(book_id: str, body: dict[str, Any], _user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """PATCH /api/v1/books/{book_id}"""
    allowed = {"title", "isbn", "description", "pubdate", "series_index"}
    sets, vals = [], []
    idx = 1
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
    if not sets:
        raise HTTPException(status_code=400, detail="No valid fields")
    vals.append(UUID(book_id))
    await execute(f"UPDATE books SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)
    return await get_book(book_id)


async def delete_book(book_id: str, _admin: Any = Depends(require_admin)) -> dict[str, bool]:
    """DELETE /api/v1/books/{book_id}"""
    await execute("DELETE FROM books WHERE id = $1", UUID(book_id))
    storage.delete_book_dir(book_id)
    return {"ok": True}


async def serve_cover(book_id: str) -> FileResponse:
    """GET /api/v1/books/{book_id}/cover — with cache headers."""
    row = await fetch_one("SELECT cover_path FROM books WHERE id = $1", UUID(book_id))
    if not row or not row["cover_path"] or not os.path.isfile(row["cover_path"]):
        raise HTTPException(status_code=404, detail="No cover")
    return FileResponse(
        row["cover_path"],
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400", "ETag": book_id},
    )


MIME_MAP = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "mobi": "application/x-mobipocket-ebook",
    "mp3": "audio/mpeg",
    "m4b": "audio/mp4",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
}


async def serve_file(book_id: str, file_id: str) -> FileResponse:
    """GET /api/v1/books/{book_id}/file/{file_id}"""
    row = await fetch_one("SELECT * FROM book_files WHERE id = $1 AND book_id = $2", UUID(file_id), UUID(book_id))
    if not row or not os.path.isfile(row["file_path"]):
        raise HTTPException(status_code=404, detail="File not found")
    mime = row["mime_type"] or MIME_MAP.get(row["format"], "") or mimetypes.guess_type(row["file_name"])[0] or "application/octet-stream"
    return FileResponse(row["file_path"], media_type=mime, filename=row["file_name"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _book_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "sort_title": row["sort_title"],
        "isbn": row["isbn"],
        "description": row["description"],
        "cover_path": row["cover_path"],
        "quality_score": row["quality_score"],
        "series_index": row["series_index"],
        "authors": row["authors"] if row["authors"] else [],
        "formats": row["formats"] if row["formats"] else [],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
