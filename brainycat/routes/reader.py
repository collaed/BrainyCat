"""Routes: reader."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from brainycat import db, opds, recommendations, scanner, sync
from brainycat.auth import get_current_user

if TYPE_CHECKING:
    from brainycat.routes.models import AnnotationCreate, BookmarkCreate, ProgressUpdate

router = APIRouter(prefix="/api/v1", tags=["reader"])


@router.get("/incoming")
async def list_incoming(status: str | None = Query(None), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await scanner.list_incoming(status)


@router.post("/incoming/scan")
async def trigger_scan(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await scanner.scan_incoming()


@router.post("/incoming/{item_id}/confirm")
async def confirm(item_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await scanner.confirm_incoming(item_id)


@router.post("/incoming/{item_id}/reject")
async def reject(item_id: str, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    return await scanner.reject_incoming(item_id)


# ── Intelligence ─────────────────────────────────────────────────────────


@router.put("/progress/{book_id}")
async def save_progress(book_id: str, body: ProgressUpdate, user: Any = Depends(get_current_user)) -> dict[str, bool]:

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


@router.get("/progress/{book_id}")
async def get_progress(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:

    row = await db.fetch_one("SELECT * FROM reading_progress WHERE user_id = $1 AND book_id = $2", user["id"], UUID(book_id))
    return dict(row) if row else {}


@router.post("/bookmarks/{book_id}")
async def add_bookmark(book_id: str, body: BookmarkCreate, user: Any = Depends(get_current_user)) -> dict[str, bool]:

    await db.execute(
        "INSERT INTO bookmarks (user_id, book_id, position, title) VALUES ($1,$2,$3,$4)",
        user["id"],
        UUID(book_id),
        body.position,
        body.title,
    )
    return {"ok": True}


@router.get("/bookmarks/{book_id}")
async def get_bookmarks(book_id: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:

    rows = await db.fetch_all("SELECT * FROM bookmarks WHERE user_id = $1 AND book_id = $2 ORDER BY created_at", user["id"], UUID(book_id))
    return [dict(r) for r in rows]


@router.post("/annotations/{book_id}")
async def add_annotation(book_id: str, body: AnnotationCreate, user: Any = Depends(get_current_user)) -> dict[str, bool]:

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


@router.get("/annotations/{book_id}")
async def get_annotations(book_id: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:

    rows = await db.fetch_all(
        "SELECT * FROM annotations WHERE user_id = $1 AND book_id = $2 ORDER BY created_at", user["id"], UUID(book_id)
    )
    return [dict(r) for r in rows]


# ── Audio restoration ────────────────────────────────────────────────────


@router.get("/sync/map/{book_id}")
async def sync_map(book_id: str, _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await sync.get_sync_map(book_id)


@router.get("/sync/position/{book_id}")
async def sync_position(
    book_id: str, from_type: str = Query("text"), position: str = Query("0"), _u: Any = Depends(get_current_user)
) -> dict[str, Any]:
    return await sync.translate_position(book_id, from_type, position)


# ── Recommendations ──────────────────────────────────────────────────────


@router.get("/recommendations/profile")
async def reco_profile(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await recommendations.build_profile(str(user["id"]))


@router.get("/recommendations/{category}")
async def reco_category(category: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await recommendations.get_recommendations(str(user["id"]), category)


# ── AI Companion ─────────────────────────────────────────────────────────


@router.get("/opds/catalog.xml")
async def opds_catalog(page: int = Query(1)) -> Any:
    return await opds.catalog(page)


@router.get("/opds/search")
async def opds_search(q: str = Query(""), page: int = Query(1)) -> Any:
    return await opds.search_opds(q, page)


# ── Podcast feeds ────────────────────────────────────────────────────────


@router.patch("/annotations/{annotation_id}/share")
async def toggle_share(annotation_id: str, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    """Toggle sharing of an annotation."""
    from uuid import UUID as _UUID

    row = await db.fetch_one("SELECT is_shared FROM annotations WHERE id = $1", _UUID(annotation_id))
    new_val = not (row["is_shared"] if row else False)
    await db.execute("UPDATE annotations SET is_shared = $1 WHERE id = $2", new_val, _UUID(annotation_id))
    return {"is_shared": new_val}


# ── Activity feed ────────────────────────────────────────────────────────


@router.get("/recommendations/{user_id}")
async def taste_recommendations(user_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.taste import get_5cat_recommendations

    return await get_5cat_recommendations(user_id)


@router.get("/taste-profile/{user_id}")
async def taste_profile(user_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.taste import build_taste_profile

    return await build_taste_profile(user_id)


# ── Multi-source aggregation ─────────────────────────────────────────────


@router.get("/recommendations/from-library")
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


@router.post("/sync/koreader")
async def koreader_sync(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Sync reading progress from KOReader. KOReader sends progress via its sync plugin."""
    body = await request.json()
    doc = body.get("document", "")
    progress = body.get("progress", 0)
    percentage = body.get("percentage", 0)
    body.get("device", "koreader")

    # Match by document hash or title
    book = await db.fetch_one("SELECT id FROM books WHERE title ILIKE $1 LIMIT 1", f"%{doc}%") if doc else None
    if not book:
        return {"error": "book not found", "document": doc}

    await db.execute(
        """
        INSERT INTO reading_progress (id, user_id, book_id, percentage, position, is_finished, updated_at)
        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, now())
        ON CONFLICT (user_id, book_id) DO UPDATE SET percentage=$3, position=$4, is_finished=$5, updated_at=now()
    """,
        user["id"],
        book["id"],
        percentage / 100.0,
        str(progress),
        percentage >= 99,
    )
    return {"ok": True, "book_id": str(book["id"]), "progress": percentage}


@router.get("/sync/koreader/progress/{document}")
async def koreader_get_progress(document: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get reading progress for KOReader to resume."""
    book = await db.fetch_one("SELECT id FROM books WHERE title ILIKE $1 LIMIT 1", f"%{document}%")
    if not book:
        return {"document": document, "progress": 0, "percentage": 0}
    rp = await db.fetch_one("SELECT percentage, position FROM reading_progress WHERE user_id=$1 AND book_id=$2", user["id"], book["id"])
    if not rp:
        return {"document": document, "progress": 0, "percentage": 0}
    return {"document": document, "progress": float(rp["position"] or 0), "percentage": round((rp["percentage"] or 0) * 100)}


# ── ISFDB (Sci-Fi/Fantasy metadata) ──────────────────────────────────────
