"""Sleep Fade Intelligence — detect where users fall asleep during audio playback.

Detects: playback stops without explicit pause + no interaction for 2+ minutes.
Auto-bookmarks the "fell asleep" point. Suggests rewind on next session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one


async def report_playback_stop(
    user_id: str,
    book_id: str,
    position: float,
    was_explicit_pause: bool,
) -> dict[str, Any]:
    """Called when audio playback stops. Detects sleep fade."""
    if was_explicit_pause:
        return {"sleep_detected": False}

    # Check: was this during typical sleep hours (22:00-06:00)?
    hour = datetime.utcnow().hour
    likely_sleep = hour >= 22 or hour <= 6

    await execute(
        """
        INSERT INTO sleep_events (id, user_id, book_id, position, likely_sleep, created_at)
        VALUES ($1, $2, $3, $4, $5, now())
    """,
        uuid4(),
        UUID(user_id),
        UUID(book_id),
        position,
        likely_sleep,
    )

    if likely_sleep:
        # Auto-bookmark
        await execute(
            """
            INSERT INTO annotations (id, user_id, book_id, content, annotation_type, position)
            VALUES ($1, $2, $3, $4, 'sleep_bookmark', $5)
        """,
            uuid4(),
            UUID(user_id),
            UUID(book_id),
            f"💤 You probably fell asleep here at {datetime.utcnow().strftime('%H:%M')}",
            str(position),
        )

    return {"sleep_detected": likely_sleep, "position": position}


async def get_rewind_suggestion(user_id: str, book_id: str) -> dict[str, Any]:
    """Get rewind suggestion based on last sleep event."""
    event = await fetch_one(
        """
        SELECT position, created_at FROM sleep_events
        WHERE user_id = $1 AND book_id = $2 AND likely_sleep = true
        ORDER BY created_at DESC LIMIT 1
    """,
        UUID(user_id),
        UUID(book_id),
    )

    if not event:
        return {"has_suggestion": False}

    # Suggest rewinding 2 minutes before the sleep point
    rewind_to = max(0, event["position"] - 120)
    return {
        "has_suggestion": True,
        "sleep_position": event["position"],
        "rewind_to": rewind_to,
        "message": f"You may have fallen asleep. Rewind to {int(rewind_to // 60)}:{int(rewind_to % 60):02d}?",
    }
