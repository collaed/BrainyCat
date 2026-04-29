"""Routes: reader."""

from __future__ import annotations

import os
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


# ── Export highlights to Markdown (Obsidian/Notion compatible) ────────────
@router.get("/books/{book_id}/export/highlights")
async def export_highlights(book_id: str, user: Any = Depends(get_current_user)) -> Any:
    """Export all highlights, annotations, and clippings as Markdown."""
    from fastapi.responses import PlainTextResponse

    book = await db.fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
    title = book["title"] if book else "Unknown"

    annotations = await db.fetch_all(
        "SELECT text, note, created_at FROM annotations WHERE user_id = $1 AND book_id = $2 ORDER BY created_at",
        user["id"],
        UUID(book_id),
    )
    clippings = await db.fetch_all(
        "SELECT text, created_at FROM clippings WHERE user_id = $1 AND book_id = $2 ORDER BY created_at",
        user["id"],
        UUID(book_id),
    )

    md = f"# {title}\n\n"
    if annotations:
        md += "## Annotations\n\n"
        for a in annotations:
            md += f"> {a['text']}\n"
            if a.get("note"):
                md += f"\n{a['note']}\n"
            md += f"\n— *{a['created_at'].strftime('%Y-%m-%d')}*\n\n"
    if clippings:
        md += "## Clippings\n\n"
        for c in clippings:
            md += f"> {c['text']}\n\n"

    return PlainTextResponse(md, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{title[:50]}.md"'})


# ── Reading goals ─────────────────────────────────────────────────────────
@router.get("/reading-goals")
async def get_reading_goals(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get reading goal progress for current year."""
    import datetime

    year = datetime.date.today().year
    finished = await db.fetch_one(
        "SELECT count(*) as cnt FROM reading_progress WHERE user_id = $1 AND is_finished = true AND updated_at >= $2",
        user["id"],
        datetime.date(year, 1, 1),
    )
    goal = await db.fetch_one(
        "SELECT target FROM reading_goals WHERE user_id = $1 AND year = $2",
        user["id"],
        year,
    )
    target = goal["target"] if goal else 0
    count = finished["cnt"] if finished else 0
    return {
        "year": year,
        "target": target,
        "completed": count,
        "progress_pct": round(count / max(target, 1) * 100) if target else 0,
    }


@router.post("/books/{book_id}/pen-annotations")
async def save_pen_annotations(book_id: str, body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Save stylus strokes for a page position."""
    import json

    cfi = body.get("cfi", "")
    pct = body.get("page_pct", 0)
    strokes = body.get("strokes", [])
    await db.execute(
        "INSERT INTO pen_annotations (user_id, book_id, cfi, page_pct, strokes) "
        "VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (user_id, book_id, cfi) DO UPDATE SET strokes = $5, updated_at = now()",
        user["id"],
        UUID(book_id),
        cfi,
        pct,
        json.dumps(strokes),
    )
    return {"ok": True}


@router.get("/books/{book_id}/pen-annotations")
async def get_pen_annotations(book_id: str, cfi: str = "", user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get stylus strokes for a page position."""
    import json

    row = await db.fetch_one(
        "SELECT strokes FROM pen_annotations WHERE user_id = $1 AND book_id = $2 AND cfi = $3",
        user["id"],
        UUID(book_id),
        cfi,
    )
    if row and row["strokes"]:
        return {"strokes": json.loads(row["strokes"]) if isinstance(row["strokes"], str) else row["strokes"]}
    return {"strokes": []}


# ── Magic Shelves ─────────────────────────────────────────────────────────
@router.get("/shelves")
async def list_shelves(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List all magic shelves with book counts."""
    from brainycat.magic_shelves import get_shelves

    return await get_shelves()


@router.get("/shelves/{shelf_id}")
async def get_shelf(shelf_id: str, limit: int = Query(50), offset: int = Query(0), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get books for a magic shelf."""
    from brainycat.magic_shelves import BUILTIN_SHELVES, get_shelf_books

    shelf = next((s for s in BUILTIN_SHELVES if s["id"] == shelf_id), None)
    if not shelf:
        return {"error": "shelf not found"}
    books = await get_shelf_books(shelf_id, limit, offset)
    return {"shelf": shelf, "books": books, "count": len(books)}


# ── Book status ───────────────────────────────────────────────────────────
@router.put("/books/{book_id}/status")
async def set_book_status(book_id: str, body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Set book status: want_to_read, reading, finished, abandoned, library."""
    status = body.get("status", "library")
    valid = {"want_to_read", "reading", "finished", "abandoned", "library"}
    if status not in valid:
        return {"error": f"Invalid status. Use: {valid}"}

    now_field = ""
    if status == "reading":
        now_field = ", started_at = COALESCE(started_at, now())"
    elif status == "finished":
        now_field = ", finished_at = now()"

    await db.execute(
        f"INSERT INTO reading_progress (user_id, book_id, status{', started_at' if status == 'reading' else ''}{', finished_at' if status == 'finished' else ''}) "
        f"VALUES ($1, $2, $3{', now()' if status == 'reading' else ''}{', now()' if status == 'finished' else ''}) "
        f"ON CONFLICT (user_id, book_id) DO UPDATE SET status = $3{now_field}",
        user["id"],
        UUID(book_id),
        status,
    )
    return {"ok": True, "status": status}


@router.get("/books/by-status/{status}")
async def books_by_status(status: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get books by reading status."""
    rows = await db.fetch_all(
        "SELECT b.id, b.title, b.cover_path, b.quality_score, rp.percentage, rp.status "
        "FROM reading_progress rp JOIN books b ON b.id = rp.book_id "
        "WHERE rp.user_id = $1 AND rp.status = $2 "
        "ORDER BY rp.updated_at DESC",
        user["id"],
        status,
    )
    return [dict(r) for r in rows]


# ── Global Notebook (all annotations across all books) ────────────────────
@router.get("/notebook")
async def global_notebook(limit: int = Query(100), q: str = Query(None), user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """All annotations, clippings, and highlights across all books — searchable."""
    query = """
        SELECT 'annotation' as type, a.text, a.note, a.created_at, b.title as book_title, b.id as book_id
        FROM annotations a JOIN books b ON b.id = a.book_id
        WHERE a.user_id = $1
    """
    params: list[Any] = [user["id"]]

    if q:
        query += " AND (a.text ILIKE $2 OR a.note ILIKE $2 OR b.title ILIKE $2)"
        params.append(f"%{q}%")

    query += " ORDER BY a.created_at DESC LIMIT $" + str(len(params) + 1)
    params.append(limit)

    annotations = await db.fetch_all(query, *params)

    # Also get clippings
    clip_query = """
        SELECT 'clipping' as type, c.text, NULL as note, c.created_at, b.title as book_title, b.id as book_id
        FROM clippings c JOIN books b ON b.id = c.book_id
        WHERE c.user_id = $1
    """
    clip_params: list[Any] = [user["id"]]
    if q:
        clip_query += " AND (c.text ILIKE $2 OR b.title ILIKE $2)"
        clip_params.append(f"%{q}%")
    clip_query += " ORDER BY c.created_at DESC LIMIT $" + str(len(clip_params) + 1)
    clip_params.append(limit)

    clippings = await db.fetch_all(clip_query, *clip_params)

    # Merge and sort
    all_items = [dict(r) for r in annotations] + [dict(r) for r in clippings]
    all_items.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    return {"items": all_items[:limit], "total": len(all_items)}


# ── Reading Streaks & Daily Log ───────────────────────────────────────────
@router.get("/reading/streak")
async def reading_streak(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get current reading streak and stats."""
    # Days with reading activity (based on progress updates)
    rows = await db.fetch_all(
        """SELECT DISTINCT date_trunc('day', updated_at)::date as day
           FROM reading_progress WHERE user_id = $1
           ORDER BY day DESC LIMIT 365""",
        user["id"],
    )
    if not rows:
        return {"current_streak": 0, "longest_streak": 0, "total_days": 0}

    from datetime import date, timedelta

    days = [r["day"] for r in rows]
    today = date.today()

    # Current streak
    current = 0
    check = today
    for d in days:
        if d == check or d == check - timedelta(days=1):
            current += 1
            check = d - timedelta(days=1)
        else:
            break

    # Longest streak
    longest = 1
    streak = 1
    for i in range(1, len(days)):
        if days[i - 1] - days[i] == timedelta(days=1):
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 1

    return {
        "current_streak": current,
        "longest_streak": longest,
        "total_days": len(days),
        "last_read": str(days[0]) if days else None,
    }


@router.post("/reading/log")
async def log_reading(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Log a reading session (minutes, pages, book)."""
    book_id = body.get("book_id")
    minutes = body.get("minutes", 0)
    pages = body.get("pages", 0)

    await db.execute(
        """INSERT INTO reading_log (user_id, book_id, minutes, pages_read, logged_at)
           VALUES ($1, $2, $3, $4, now())""",
        user["id"],
        UUID(book_id) if book_id else None,
        minutes,
        pages,
    )
    return {"ok": True}


@router.get("/reading/stats")
async def reading_stats(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Reading stats: this week, this month, this year."""
    row = await db.fetch_one(
        """SELECT
            count(*) FILTER (WHERE logged_at > now() - interval '7 days') as week_sessions,
            COALESCE(sum(minutes) FILTER (WHERE logged_at > now() - interval '7 days'), 0) as week_minutes,
            count(*) FILTER (WHERE logged_at > now() - interval '30 days') as month_sessions,
            COALESCE(sum(minutes) FILTER (WHERE logged_at > now() - interval '30 days'), 0) as month_minutes,
            count(*) as total_sessions,
            COALESCE(sum(minutes), 0) as total_minutes
           FROM reading_log WHERE user_id = $1""",
        user["id"],
    )
    return dict(row) if row else {}


# ── Download with embedded annotations ────────────────────────────────────
@router.get("/books/{book_id}/download-annotated")
async def download_annotated(book_id: str, user: Any = Depends(get_current_user)) -> Any:
    """Download PDF with annotations embedded (permanent highlights)."""
    import shutil
    import tempfile

    import fitz
    from fastapi.responses import FileResponse

    row = await db.fetch_one(
        "SELECT bf.file_path, bf.file_name FROM book_files bf WHERE bf.book_id = $1 AND bf.format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"error": "no pdf"}

    annotations = await db.fetch_all(
        "SELECT page_num, text FROM annotations WHERE book_id = $1 AND user_id = $2 AND page_num IS NOT NULL",
        UUID(book_id),
        user["id"],
    )

    if not annotations:
        return FileResponse(row["file_path"], filename=row["file_name"])

    # Copy to temp, embed annotations, serve
    tmp = tempfile.mktemp(suffix=".pdf")
    shutil.copy2(row["file_path"], tmp)
    doc = fitz.open(tmp)
    for ann in annotations:
        if ann["page_num"] < 0 or ann["page_num"] >= len(doc):
            continue
        page = doc[ann["page_num"]]
        instances = page.search_for((ann["text"] or "")[:100])
        if instances:
            h = page.add_highlight_annot(instances)
            if h:
                h.set_colors(stroke=(1, 0.8, 0))
                h.update()
    doc.save(tmp, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    return FileResponse(tmp, filename=row["file_name"], media_type="application/pdf")


# ── Reading Goals ─────────────────────────────────────────────────────────
@router.put("/reading/goal")
async def set_reading_goal(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Set a reading goal (e.g., 50 books in 2026)."""
    year = body.get("year", 2026)
    target = body.get("target", 12)
    goal_type = body.get("type", "books")  # books or minutes

    await db.execute(
        """INSERT INTO reading_goals (user_id, year, target, goal_type)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, year, goal_type) DO UPDATE SET target = $3""",
        user["id"],
        year,
        target,
        goal_type,
    )
    return {"ok": True, "year": year, "target": target, "type": goal_type}


@router.get("/reading/goal")
async def get_reading_goal(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get reading goal progress for current year."""
    from datetime import date

    year = date.today().year
    goal = await db.fetch_one(
        "SELECT target, goal_type FROM reading_goals WHERE user_id = $1 AND year = $2",
        user["id"],
        year,
    )
    if not goal:
        return {"goal": None}

    if goal["goal_type"] == "books":
        progress = await db.fetch_one(
            """SELECT count(DISTINCT book_id) as completed
               FROM reading_progress WHERE user_id = $1 AND status = 'finished'
               AND extract(year from finished_at) = $2""",
            user["id"],
            year,
        )
        current = progress["completed"] if progress else 0
    else:
        progress = await db.fetch_one(
            "SELECT COALESCE(sum(minutes), 0) as total FROM reading_log WHERE user_id = $1 AND extract(year from logged_at) = $2",
            user["id"],
            year,
        )
        current = progress["total"] if progress else 0

    return {
        "year": year,
        "target": goal["target"],
        "current": current,
        "type": goal["goal_type"],
        "percentage": round(current / goal["target"] * 100, 1) if goal["target"] > 0 else 0,
    }


# ── Collections ───────────────────────────────────────────────────────────
@router.post("/collections")
async def create_collection(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Create a book collection."""
    name = body.get("name", "")
    description = body.get("description", "")
    row = await db.fetch_one(
        "INSERT INTO collections (user_id, name, description) VALUES ($1, $2, $3) RETURNING id",
        user["id"],
        name,
        description,
    )
    return {"id": str(row["id"]), "name": name}


@router.get("/collections")
async def list_collections(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List user's collections with book counts."""
    rows = await db.fetch_all(
        """SELECT c.id, c.name, c.description, count(cb.book_id) as book_count
           FROM collections c LEFT JOIN collection_books cb ON cb.collection_id = c.id
           WHERE c.user_id = $1 GROUP BY c.id ORDER BY c.name""",
        user["id"],
    )
    return [dict(r) for r in rows]


@router.post("/collections/{collection_id}/books")
async def add_to_collection(collection_id: str, body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add a book to a collection."""
    book_id = body.get("book_id")
    await db.execute(
        "INSERT INTO collection_books (collection_id, book_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        UUID(collection_id),
        UUID(book_id),
    )
    return {"ok": True}


@router.delete("/collections/{collection_id}/books/{book_id}")
async def remove_from_collection(collection_id: str, book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Remove a book from a collection."""
    await db.execute(
        "DELETE FROM collection_books WHERE collection_id = $1 AND book_id = $2",
        UUID(collection_id),
        UUID(book_id),
    )
    return {"ok": True}


@router.get("/collections/{collection_id}/books")
async def collection_books(collection_id: str, user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get books in a collection."""
    rows = await db.fetch_all(
        """SELECT b.id, b.title, b.cover_path, b.quality_score
           FROM collection_books cb JOIN books b ON b.id = cb.book_id
           WHERE cb.collection_id = $1 ORDER BY cb.added_at DESC""",
        UUID(collection_id),
    )
    return [dict(r) for r in rows]


# ── OPDS Page Streaming ───────────────────────────────────────────────────
@router.get("/opds-ps/{book_id}/manifest")
async def opds_ps_manifest(book_id: str) -> dict[str, Any]:
    """OPDS-PS manifest — page count and streaming info."""
    import fitz

    row = await db.fetch_one(
        "SELECT bf.file_path, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 AND bf.format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no pdf"}
    doc = fitz.open(row["file_path"])
    pages = len(doc)
    doc.close()
    return {
        "title": row["title"],
        "pages": pages,
        "page_url": f"/api/v1/opds-ps/{book_id}/page/{{page}}",
        "media_type": "image/png",
    }


@router.get("/opds-ps/{book_id}/page/{page_num}")
async def opds_ps_page(book_id: str, page_num: int, width: int = 1200) -> Any:
    """Serve a single page as WebP for OPDS-PS streaming."""
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
    # Scale to requested width
    scale = width / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    img_bytes = pix.tobytes("png")
    doc.close()

    return Response(content=img_bytes, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ── Reading Time Estimator ────────────────────────────────────────────────
@router.get("/books/{book_id}/reading-time")
async def reading_time_estimate(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Estimate time to finish based on user's reading pace."""
    # Get book page/word count
    book = await db.fetch_one(
        "SELECT page_count, word_count, estimated_reading_minutes FROM books WHERE id = $1",
        UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    # Get user's average pace from reading_log
    pace = await db.fetch_one(
        """SELECT CASE WHEN sum(pages_read) > 0
            THEN sum(minutes)::float / sum(pages_read)
            ELSE 1.5 END as min_per_page
           FROM reading_log WHERE user_id = $1 AND pages_read > 0""",
        user["id"],
    )
    min_per_page = pace["min_per_page"] if pace else 1.5

    # Get current progress
    progress = await db.fetch_one(
        "SELECT percentage FROM reading_progress WHERE user_id = $1 AND book_id = $2",
        user["id"],
        UUID(book_id),
    )
    pct_done = (progress["percentage"] or 0) / 100 if progress else 0

    pages = book["page_count"] or 300
    remaining_pages = pages * (1 - pct_done)
    est_minutes = int(remaining_pages * min_per_page)

    return {
        "total_pages": pages,
        "pages_remaining": int(remaining_pages),
        "minutes_remaining": est_minutes,
        "hours_remaining": round(est_minutes / 60, 1),
        "pace_min_per_page": round(min_per_page, 2),
        "percentage_done": round(pct_done * 100, 1),
    }


# ── Reading Speed Test ────────────────────────────────────────────────────
@router.post("/reading/speed-test")
async def reading_speed_test(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Record a reading speed test result. Body: {words: int, seconds: int}."""
    words = body.get("words", 0)
    seconds = body.get("seconds", 1)
    wpm = int(words / (seconds / 60))

    await db.execute(
        "UPDATE users SET preferences = jsonb_set(COALESCE(preferences, '{}'), '{reading_wpm}', $1::jsonb) WHERE id = $2",
        str(wpm),
        user["id"],
    )
    return {"wpm": wpm, "pages_per_hour": round(wpm / 250 * 60 / 1.5, 1)}


@router.get("/reading/speed")
async def get_reading_speed(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get user's calibrated reading speed."""
    row = await db.fetch_one("SELECT preferences->'reading_wpm' as wpm FROM users WHERE id = $1", user["id"])
    wpm = int(row["wpm"]) if row and row["wpm"] else 250
    return {"wpm": wpm, "pages_per_hour": round(wpm / 250 * 60 / 1.5, 1)}
