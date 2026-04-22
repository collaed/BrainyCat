"""Book Club — pace-locked chapters with spoiler-safe discussions.

Users create a club, set a book + reading pace. Chapters unlock on schedule.
Discussion threads per chapter — you can't see discussions for chapters
you haven't reached.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all, fetch_one


async def create_club(
    creator_id: str,
    name: str,
    book_id: str,
    chapters_per_week: int = 3,
    start_date: str | None = None,
) -> dict[str, Any]:
    """Create a book club with a reading pace."""
    cid = uuid4()
    start = datetime.fromisoformat(start_date) if start_date else datetime.utcnow()
    await execute(
        """
        INSERT INTO book_clubs (id, creator_id, name, book_id, chapters_per_week, start_date)
        VALUES ($1, $2, $3, $4, $5, $6)
    """,
        cid,
        UUID(creator_id),
        name,
        UUID(book_id),
        chapters_per_week,
        start,
    )
    # Auto-join creator
    await execute("INSERT INTO club_members (id, club_id, user_id) VALUES ($1,$2,$3)", uuid4(), cid, UUID(creator_id))
    return {"id": str(cid), "name": name}


async def join_club(club_id: str, user_id: str) -> dict[str, Any]:
    await execute(
        "INSERT INTO club_members (id, club_id, user_id) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        uuid4(),
        UUID(club_id),
        UUID(user_id),
    )
    return {"ok": True}


async def get_club(club_id: str, user_id: str) -> dict[str, Any]:
    """Get club details with pace-locked chapter access."""
    club = await fetch_one("SELECT * FROM book_clubs WHERE id = $1", UUID(club_id))
    if not club:
        return {"error": "not found"}

    # Calculate which chapters are unlocked
    start = club["start_date"]
    pace = club["chapters_per_week"] or 3
    weeks_elapsed = max(0, (datetime.utcnow() - start).days / 7)
    unlocked_chapters = int(weeks_elapsed * pace) + 1  # At least chapter 1

    # Get discussions only for unlocked chapters
    discussions = await fetch_all(
        """
        SELECT cd.chapter_number, cd.content, cd.created_at, u.username
        FROM club_discussions cd
        JOIN users u ON u.id = cd.user_id
        WHERE cd.club_id = $1 AND cd.chapter_number <= $2
        ORDER BY cd.chapter_number, cd.created_at
    """,
        UUID(club_id),
        unlocked_chapters,
    )

    members = await fetch_all(
        """
        SELECT u.username, rp.percentage FROM club_members cm
        JOIN users u ON u.id = cm.user_id
        LEFT JOIN reading_progress rp ON rp.book_id = $2 AND rp.user_id = cm.user_id
        WHERE cm.club_id = $1
    """,
        UUID(club_id),
        club["book_id"],
    )

    return {
        "id": str(club["id"]),
        "name": club["name"],
        "book_id": str(club["book_id"]),
        "unlocked_chapters": unlocked_chapters,
        "chapters_per_week": pace,
        "members": [{"username": m["username"], "progress": round((m["percentage"] or 0) * 100)} for m in members],
        "discussions": [dict(d) for d in discussions],
    }


async def post_discussion(club_id: str, user_id: str, chapter: int, content: str) -> dict[str, Any]:
    """Post to a chapter discussion (only if chapter is unlocked)."""
    club = await fetch_one("SELECT * FROM book_clubs WHERE id = $1", UUID(club_id))
    if not club:
        return {"error": "not found"}
    start = club["start_date"]
    pace = club["chapters_per_week"] or 3
    weeks_elapsed = max(0, (datetime.utcnow() - start).days / 7)
    unlocked = int(weeks_elapsed * pace) + 1
    if chapter > unlocked:
        return {"error": f"chapter {chapter} not unlocked yet (current: {unlocked})"}

    await execute(
        """
        INSERT INTO club_discussions (id, club_id, user_id, chapter_number, content)
        VALUES ($1, $2, $3, $4, $5)
    """,
        uuid4(),
        UUID(club_id),
        UUID(user_id),
        chapter,
        content,
    )
    return {"ok": True}
