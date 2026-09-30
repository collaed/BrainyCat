"""Routes: social."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect

from brainycat import db, podcast
from brainycat.auth import get_current_user, require_admin

_active_readers: dict[str, Any] = {}

router = APIRouter(prefix="/api/v1", tags=["social"])


@router.get("/feeds/{feed_id}/rss")
async def podcast_rss(feed_id: str) -> Any:
    """Serve the RSS feed for a podcast feed. GET /api/v1/feeds/{feed_id}/rss, fetched by podcast clients, not the web UI."""
    return await podcast.get_rss(feed_id)


# ── Import ───────────────────────────────────────────────────────────────


@router.get("/feed/recent.xml")
async def recent_feed() -> Any:
    """Build an Atom feed of the 20 most recently added books. GET /api/v1/feed/recent.xml, no frontend caller found — meant for external feed readers."""
    from fastapi.responses import Response

    books_list = await db.fetch_all("SELECT id, title, updated_at FROM books ORDER BY created_at DESC LIMIT 20")
    entries = "\n".join(
        f"<entry><id>urn:brainycat:{r['id']}</id><title>{r['title']}</title><updated>{r['updated_at'].isoformat() if r['updated_at'] else ''}</updated></entry>"
        for r in books_list
    )
    xml = f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><id>urn:brainycat:recent</id><title>BrainyCat — Recent</title>{entries}</feed>'
    return Response(content=xml, media_type="application/atom+xml")


# ── Covers ───────────────────────────────────────────────────────────────


@router.websocket("/ws/activity")
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


@router.post("/activity/reading")
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


@router.get("/activity/feed")
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


@router.post("/social/enable-profile")
async def enable_profile(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Turn on the current user's public profile. POST /api/v1/social/enable-profile, delegates to `brainycat.social.enable_public_profile`; no frontend caller found."""
    from brainycat.social import enable_public_profile

    return await enable_public_profile(str(user["id"]), "localhost")


@router.get("/social/following")
async def get_following(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List the users the current user follows. GET /api/v1/social/following, delegates to `brainycat.social.list_following`; no frontend caller found."""
    from brainycat.social import list_following

    return await list_following(str(user["id"]))


@router.post("/social/follow")
async def follow(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Follow another user by their profile hash. POST /api/v1/social/follow, delegates to `brainycat.social.follow_user`; no frontend caller found."""
    from brainycat.social import follow_user

    body = await request.json()
    return await follow_user(str(user["id"]), body["hash"])


@router.post("/social/refresh")
async def refresh_social(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Refresh the current user's followed-feed data. POST /api/v1/social/refresh, delegates to `brainycat.social.refresh_follows`; no frontend caller found."""
    from brainycat.social import refresh_follows

    return await refresh_follows(str(user["id"]))


@router.get("/public/{username}/feed.json")
async def public_feed(username: str) -> dict[str, Any]:
    """Public feed endpoint — no auth required, polled by followers."""
    from brainycat.social import get_public_feed

    return await get_public_feed(username)


# ── Book Clubs ───────────────────────────────────────────────────────────


@router.post("/clubs")
async def create_book_club(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Create a new book club. POST /api/v1/clubs, delegates to `brainycat.book_clubs.create_club`; no frontend caller found."""
    from brainycat.book_clubs import create_club

    body = await request.json()
    return await create_club(str(user["id"]), body["name"], body["book_id"], body.get("chapters_per_week", 3), body.get("start_date"))


@router.get("/clubs/{club_id}")
async def get_book_club(club_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Fetch a single book club's details. GET /api/v1/clubs/{club_id}, delegates to `brainycat.book_clubs.get_club`; no frontend caller found."""
    from brainycat.book_clubs import get_club

    return await get_club(club_id, str(user["id"]))


@router.post("/clubs/{club_id}/join")
async def join_book_club(club_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Join a book club. POST /api/v1/clubs/{club_id}/join, delegates to `brainycat.book_clubs.join_club`; no frontend caller found."""
    from brainycat.book_clubs import join_club

    return await join_club(club_id, str(user["id"]))


@router.post("/clubs/{club_id}/discuss")
async def club_discuss(club_id: str, request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Post a discussion comment for a book club chapter. POST /api/v1/clubs/{club_id}/discuss, delegates to `brainycat.book_clubs.post_discussion`; no frontend caller found."""
    from brainycat.book_clubs import post_discussion

    body = await request.json()
    return await post_discussion(club_id, str(user["id"]), body["chapter"], body["content"])


# ── Sleep Fade ───────────────────────────────────────────────────────────


@router.post("/sleep/report")
async def sleep_report(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Report that audiobook playback stopped, for sleep-fade tracking. POST /api/v1/sleep/report, called from static/player.html when playback stops; delegates to `brainycat.sleep_fade.report_playback_stop`."""
    from brainycat.sleep_fade import report_playback_stop

    body = await request.json()
    return await report_playback_stop(str(user["id"]), body["book_id"], body["position"], body.get("explicit_pause", False))


@router.get("/sleep/rewind/{book_id}")
async def sleep_rewind(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get a suggested rewind position after a sleep-fade stop. GET /api/v1/sleep/rewind/{book_id}, called from static/player.html on resume; delegates to `brainycat.sleep_fade.get_rewind_suggestion`."""
    from brainycat.sleep_fade import get_rewind_suggestion

    return await get_rewind_suggestion(str(user["id"]), book_id)


# ── Lending ──────────────────────────────────────────────────────────────


@router.post("/lending/request")
async def lend_request(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Request to borrow a book from another server. POST /api/v1/lending/request, delegates to `brainycat.lending.request_lend`; no frontend caller found."""
    from brainycat.lending import request_lend

    body = await request.json()
    return await request_lend(str(user["id"]), body["book_id"], body.get("server_url", ""), body.get("owner", ""), body.get("message", ""))


@router.get("/lending/incoming")
async def lending_incoming(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List incoming lending requests for the current user's books. GET /api/v1/lending/incoming, delegates to `brainycat.lending.list_incoming_requests`; no frontend caller found."""
    from brainycat.lending import list_incoming_requests

    return await list_incoming_requests(str(user["id"]))


@router.post("/lending/{request_id}/approve")
async def lending_approve(request_id: str, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Approve a pending lending request (admin only). POST /api/v1/lending/{request_id}/approve, delegates to `brainycat.lending.approve_request`; no frontend caller found."""
    from brainycat.lending import approve_request

    return await approve_request(request_id, "")


@router.post("/lending/{request_id}/deny")
async def lending_deny(request_id: str, _a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Deny a pending lending request (admin only). POST /api/v1/lending/{request_id}/deny, delegates to `brainycat.lending.deny_request`; no frontend caller found."""
    from brainycat.lending import deny_request

    return await deny_request(request_id)


# ── Streaks & Challenges ─────────────────────────────────────────────────


@router.get("/streaks")
async def get_streaks(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get the current user's reading streak. GET /api/v1/streaks, delegates to `brainycat.streaks.get_streak`; no frontend caller found (stats.html's streak counter uses /stats/overview instead)."""
    from brainycat.streaks import get_streak

    return await get_streak(str(user["id"]))


@router.get("/challenges")
async def get_challenges_list(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List the current user's reading challenges. GET /api/v1/challenges, delegates to `brainycat.streaks.get_challenges`; no frontend caller found."""
    from brainycat.streaks import get_challenges

    return await get_challenges(str(user["id"]))


@router.post("/challenges")
async def create_challenge_endpoint(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Create a new reading challenge for the current user. POST /api/v1/challenges, delegates to `brainycat.streaks.create_challenge`; no frontend caller found."""
    from brainycat.streaks import create_challenge

    body = await request.json()
    return await create_challenge(str(user["id"]), body["name"], body["target"], body.get("year"))


# ── Contextual Footnotes ─────────────────────────────────────────────────


@router.get("/quotes/random")
async def random_quote(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get a random quote from books the user has read. For ambient display."""
    row = await db.fetch_one(
        """
        SELECT b.title, b.extra_metadata->'summary'->'quotable_passages' as quotes,
               b.extra_metadata->'summary'->'takeaways' as takeaways,
               b.extra_metadata->'summary'->'key_insight' as insight,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM reading_progress rp
        JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE rp.user_id = $1 AND rp.is_finished = true
          AND b.extra_metadata IS NOT NULL AND b.extra_metadata != '{}'::jsonb
        GROUP BY b.id ORDER BY random() LIMIT 1
    """,
        user["id"],
    )
    if not row:
        # Fallback: any book with a description
        row = await db.fetch_one("""
            SELECT b.title, b.description,
                   array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
            FROM books b
            LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
            WHERE b.description IS NOT NULL AND length(b.description) > 100
            GROUP BY b.id ORDER BY random() LIMIT 1
        """)
        if row:
            return {"quote": (row["description"] or "")[:200] + "...", "book": row["title"], "authors": row["authors"] or []}
        return {"quote": "Start reading to see quotes from your library here.", "book": "BrainyCat", "authors": []}

    # Pick from available quote sources
    import json
    import random

    quotes = []
    for field in ["quotes", "takeaways"]:
        val = row.get(field)
        if val:
            parsed = json.loads(val) if isinstance(val, str) else val
            if isinstance(parsed, list):
                quotes.extend(parsed)
    if row.get("insight"):
        val = row["insight"]
        quotes.append(json.loads(val) if isinstance(val, str) else val)

    if quotes:
        q = random.choice(quotes)
        return {"quote": q if isinstance(q, str) else str(q), "book": row["title"], "authors": row["authors"] or []}
    return {"quote": row["title"], "book": row["title"], "authors": row["authors"] or []}


# ── Reading feeds (web-to-ebook) ──────────────────────────────────────────


@router.get("/feeds")
async def get_feeds(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List the current user's web-to-ebook reading feeds. GET /api/v1/feeds, delegates to `brainycat.reading_feed.list_feeds`; no frontend caller found."""
    from brainycat.reading_feed import list_feeds

    return await list_feeds(str(user["id"]))


@router.post("/feeds")
async def add_feed_endpoint(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Add a new web-to-ebook reading feed. POST /api/v1/feeds, delegates to `brainycat.reading_feed.add_feed`; no frontend caller found."""
    from brainycat.reading_feed import add_feed

    body = await request.json()
    return await add_feed(str(user["id"]), body["url"], body.get("name", ""))


@router.delete("/feeds/{feed_id}")
async def remove_feed_endpoint(feed_id: str, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    """Delete a web-to-ebook reading feed. DELETE /api/v1/feeds/{feed_id}, delegates to `brainycat.reading_feed.remove_feed`; no frontend caller found."""
    from brainycat.reading_feed import remove_feed

    return await remove_feed(feed_id, str(user["id"]))


@router.post("/feeds/{feed_id}/fetch")
async def fetch_feed_endpoint(feed_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Trigger an immediate fetch of a reading feed's new entries. POST /api/v1/feeds/{feed_id}/fetch, delegates to `brainycat.reading_feed.fetch_feed`; no frontend caller found."""
    from brainycat.reading_feed import fetch_feed

    return await fetch_feed(feed_id)


# ── Title cleanup ─────────────────────────────────────────────────────────
