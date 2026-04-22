"""Reading Streaks & Challenges — Duolingo-style gamification."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all, fetch_one


async def get_streak(user_id: str) -> dict[str, Any]:
    """Calculate current reading streak (consecutive days with reading activity)."""
    rows = await fetch_all(
        """
        SELECT DISTINCT DATE(updated_at) as day FROM reading_progress
        WHERE user_id = $1 AND percentage > 0
        ORDER BY day DESC LIMIT 365
    """,
        UUID(user_id),
    )

    if not rows:
        return {"current_streak": 0, "longest_streak": 0, "today": False}

    days = [r["day"] for r in rows]
    today = date.today()

    # Current streak
    current = 0
    check = today
    for d in days:
        if d == check:
            current += 1
            check -= timedelta(days=1)
        elif d < check:
            break

    # Longest streak
    longest = 1
    run = 1
    for i in range(1, len(days)):
        if days[i] == days[i - 1] - timedelta(days=1):
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    return {
        "current_streak": current,
        "longest_streak": longest,
        "today": days[0] == today if days else False,
        "last_active": days[0].isoformat() if days else None,
    }


async def create_challenge(user_id: str, name: str, target: int, year: int | None = None) -> dict[str, Any]:
    """Create a reading challenge (e.g., 'Read 50 books in 2026')."""
    cid = uuid4()
    yr = year or date.today().year
    await execute(
        """
        INSERT INTO reading_challenges (id, user_id, name, target_books, year)
        VALUES ($1, $2, $3, $4, $5)
    """,
        cid,
        UUID(user_id),
        name,
        target,
        yr,
    )
    return {"id": str(cid), "name": name, "target": target, "year": yr}


async def get_challenges(user_id: str) -> list[dict[str, Any]]:
    """Get all challenges with progress."""
    challenges = await fetch_all(
        "SELECT * FROM reading_challenges WHERE user_id = $1 ORDER BY year DESC",
        UUID(user_id),
    )
    result = []
    for c in challenges:
        finished = await fetch_one(
            """
            SELECT count(*) as n FROM reading_progress
            WHERE user_id = $1 AND is_finished = true
            AND EXTRACT(YEAR FROM updated_at) = $2
        """,
            UUID(user_id),
            c["year"],
        )
        progress = finished["n"] if finished else 0
        result.append(
            {
                "id": str(c["id"]),
                "name": c["name"],
                "target": c["target_books"],
                "year": c["year"],
                "progress": progress,
                "percentage": round(progress / max(c["target_books"], 1) * 100),
                "completed": progress >= c["target_books"],
            }
        )
    return result
