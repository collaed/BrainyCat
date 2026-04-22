"""ABS (Audiobookshelf) API compatibility shim.

Translates BrainyCat's PostgreSQL data into ABS's exact JSON response shapes.
This lets the ABS mobile apps (iOS + Android, 30K+ users) connect to BrainyCat
as if it were an ABS server.

Routes: /compat/abs/api/* mirrors ABS's API structure.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from brainycat.auth import get_current_user
from brainycat.db import fetch_all, fetch_one

router = APIRouter(prefix="/compat/abs")


def _ts(dt: Any) -> int:
    """Convert datetime to millisecond timestamp."""
    if dt is None:
        return int(time.time() * 1000)
    try:
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def _book_to_abs_minified(book: dict, files: list[dict] | None = None) -> dict:
    """Convert a BrainyCat book to ABS LibraryItem minified JSON."""
    files = files or []
    audio_files = [f for f in files if f.get("format") in ("mp3", "m4b", "m4a", "flac", "ogg")]
    ebook_file = next((f for f in files if f.get("format") in ("epub", "pdf", "mobi", "azw3")), None)
    duration = sum(f.get("duration", 0) for f in audio_files)

    authors = book.get("authors") or []
    author_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
    tags = book.get("tags") or []

    return {
        "id": str(book["id"]),
        "ino": str(book["id"])[:12],
        "oldLibraryItemId": None,
        "libraryId": "main",
        "folderId": "main",
        "path": f"/data/books/{book['id']}",
        "relPath": str(book.get("title", "")),
        "isFile": False,
        "mtimeMs": _ts(book.get("updated_at")),
        "ctimeMs": _ts(book.get("created_at")),
        "birthtimeMs": _ts(book.get("created_at")),
        "addedAt": _ts(book.get("created_at")),
        "updatedAt": _ts(book.get("updated_at")),
        "isMissing": False,
        "isInvalid": False,
        "mediaType": "book",
        "media": {
            "id": str(book["id"]),
            "metadata": {
                "title": book.get("title", ""),
                "titleIgnorePrefix": book.get("title", ""),
                "subtitle": "",
                "authorName": author_str,
                "authorNameLF": author_str,
                "narratorName": "",
                "seriesName": "",
                "genres": tags if isinstance(tags, list) else [],
                "publishedYear": "",
                "publishedDate": "",
                "publisher": "",
                "description": (book.get("description") or "")[:500],
                "isbn": book.get("isbn") or "",
                "asin": "",
                "language": book.get("language") or "en",
                "explicit": False,
                "abridged": False,
            },
            "coverPath": f"/data/covers/{book['id']}.jpg" if book.get("cover_path") else None,
            "tags": tags if isinstance(tags, list) else [],
            "numTracks": len(audio_files),
            "numAudioFiles": len(audio_files),
            "numChapters": len(audio_files) or 1,
            "duration": duration,
            "size": sum(f.get("file_size", 0) for f in files),
            "ebookFormat": ebook_file["format"] if ebook_file else None,
        },
        "numFiles": len(files),
        "size": sum(f.get("file_size", 0) for f in files),
    }


# ── Auth ─────────────────────────────────────────────────────────────────


@router.post("/login")
async def abs_login(request: Request) -> JSONResponse:
    """ABS login — returns JWT-like token."""
    import secrets

    body = await request.json()
    username = body.get("username", "")
    user = await fetch_one("SELECT * FROM users WHERE username = $1", username)
    if not user:
        return JSONResponse({"error": "Invalid login"}, status_code=401)

    token = secrets.token_urlsafe(32)
    return JSONResponse(
        {
            "user": {
                "id": str(user["id"]),
                "username": user["username"],
                "type": "admin" if user.get("role") == "admin" else "user",
                "token": token,
                "mediaProgress": [],
                "seriesHideFromContinueListening": [],
                "bookmarks": [],
                "isActive": True,
                "isLocked": False,
                "permissions": {"download": True, "update": True, "delete": True, "upload": True},
            }
        }
    )


# ── User ─────────────────────────────────────────────────────────────────


@router.get("/api/me")
async def abs_me(user: Any = Depends(get_current_user)) -> dict:
    """ABS user profile with mediaProgress."""
    progress = await fetch_all(
        """
        SELECT rp.book_id, rp.percentage, rp.position_timestamp, rp.is_finished, rp.updated_at
        FROM reading_progress rp WHERE rp.user_id = $1
    """,
        user["id"],
    )

    return {
        "id": str(user["id"]),
        "username": user["username"],
        "type": "admin" if user.get("role") == "admin" else "user",
        "mediaProgress": [
            {
                "id": str(p["book_id"]),
                "libraryItemId": str(p["book_id"]),
                "duration": 0,
                "progress": p["percentage"] or 0,
                "currentTime": p["position_timestamp"] or 0,
                "isFinished": p["is_finished"] or False,
                "lastUpdate": _ts(p["updated_at"]),
                "startedAt": _ts(p["updated_at"]),
                "finishedAt": _ts(p["updated_at"]) if p["is_finished"] else None,
            }
            for p in progress
        ],
        "bookmarks": [],
        "isActive": True,
    }


# ── Libraries ────────────────────────────────────────────────────────────


@router.get("/api/libraries")
async def abs_libraries(_u: Any = Depends(get_current_user)) -> dict:
    total = await fetch_one("SELECT count(*) as n FROM books")
    return {
        "libraries": [
            {
                "id": "main",
                "name": "BrainyCat Library",
                "folders": [{"id": "main", "fullPath": "/data/books"}],
                "mediaType": "book",
                "stats": {"totalItems": total["n"] if total else 0},
            }
        ]
    }


# ── Library Items ────────────────────────────────────────────────────────


@router.get("/api/libraries/{library_id}/items")
async def abs_library_items(
    library_id: str,
    limit: int = Query(50),
    page: int = Query(0),
    sort: str = Query("addedAt"),
    desc: int = Query(1),
    _u: Any = Depends(get_current_user),
) -> dict:
    offset = page * limit
    order = "DESC" if desc else "ASC"
    sort_col = {"addedAt": "b.created_at", "media.metadata.title": "b.title", "updatedAt": "b.updated_at"}.get(sort, "b.created_at")

    books = await fetch_all(
        f"""
        SELECT b.id, b.title, b.description, b.isbn, b.cover_path, COALESCE(b.language, '') as language,
               b.created_at, b.updated_at,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        GROUP BY b.id ORDER BY {sort_col} {order} LIMIT $1 OFFSET $2
    """,
        limit,
        offset,
    )

    total = await fetch_one("SELECT count(*) as n FROM books")

    return {
        "results": [_book_to_abs_minified(dict(b)) for b in books],
        "total": total["n"] if total else 0,
        "limit": limit,
        "page": page,
    }


# ── Single Item ──────────────────────────────────────────────────────────


@router.get("/api/items/{item_id}")
async def abs_item(item_id: str, _u: Any = Depends(get_current_user)) -> dict:
    book = await fetch_one(
        """
        SELECT b.*, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        UUID(item_id),
    )
    if not book:
        return {"error": "not found"}

    files = await fetch_all("SELECT * FROM book_files WHERE book_id = $1", UUID(item_id))
    return _book_to_abs_minified(dict(book), [dict(f) for f in files])


# ── Cover ────────────────────────────────────────────────────────────────


@router.get("/api/items/{item_id}/cover")
async def abs_cover(item_id: str) -> Any:
    from fastapi.responses import FileResponse

    book = await fetch_one("SELECT cover_path FROM books WHERE id = $1", UUID(item_id))
    if book and book["cover_path"] and __import__("os").path.isfile(book["cover_path"]):
        return FileResponse(book["cover_path"], media_type="image/jpeg")
    return JSONResponse({"error": "no cover"}, status_code=404)


# ── Progress ─────────────────────────────────────────────────────────────


@router.patch("/api/me/progress/{item_id}")
async def abs_update_progress(item_id: str, request: Request, user: Any = Depends(get_current_user)) -> dict:
    from brainycat.db import execute

    body = await request.json()
    await execute(
        """
        INSERT INTO reading_progress (id, user_id, book_id, percentage, position_timestamp, is_finished)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, book_id) DO UPDATE SET
            percentage = EXCLUDED.percentage, position_timestamp = EXCLUDED.position_timestamp,
            is_finished = EXCLUDED.is_finished, updated_at = now()
    """,
        uuid4(),
        user["id"],
        UUID(item_id),
        body.get("progress", 0),
        body.get("currentTime", 0),
        body.get("isFinished", False),
    )
    return {"success": True}


@router.get("/api/me/items-in-progress")
async def abs_in_progress(user: Any = Depends(get_current_user)) -> dict:
    rows = await fetch_all(
        """
        SELECT b.id, b.title, b.description, b.isbn, b.cover_path, COALESCE(b.language, '') as language,
               b.created_at, b.updated_at,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               rp.percentage, rp.position_timestamp
        FROM reading_progress rp
        JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE rp.user_id = $1 AND rp.is_finished = false AND rp.percentage > 0
        GROUP BY b.id, rp.percentage, rp.position_timestamp
        ORDER BY rp.updated_at DESC LIMIT 20
    """,
        user["id"],
    )
    return {"libraryItems": [_book_to_abs_minified(dict(r)) for r in rows]}
