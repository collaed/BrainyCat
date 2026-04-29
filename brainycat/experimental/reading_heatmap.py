"""Reading heatmap — daily reading activity calendar.

Returns reading minutes per day for the last N days.
Frontend renders as a GitHub-style contribution graph.

Config: BRAINYCAT_EXP_HEATMAP=1
"""

from __future__ import annotations

from typing import Any


async def get_heatmap(user_id: str, days: int = 365) -> list[dict[str, Any]]:
    """Get daily reading minutes for heatmap visualization."""
    from brainycat.db import fetch_all

    rows = await fetch_all(
        """
        SELECT date_trunc('day', updated_at)::date as day,
               count(*) as sessions,
               count(DISTINCT book_id) as books_touched
        FROM reading_progress
        WHERE user_id = $1 AND updated_at > now() - make_interval(days => $2)
        GROUP BY 1 ORDER BY 1
        """,
        user_id,
        days,
    )
    return [{"date": str(r["day"]), "sessions": r["sessions"], "books": r["books_touched"]} for r in rows]
