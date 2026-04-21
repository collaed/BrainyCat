"""Podcast RSS feed for drip-scheduled audiobook chapters."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi.responses import Response

from brainycat.db import execute, fetch_all, fetch_one


async def create_feed(book_id: str, user_id: str, schedule: str = "daily", release_time: str = "08:00") -> dict[str, Any]:
    fid = uuid4()
    await execute(
        "INSERT INTO podcast_feeds (id, book_id, user_id, schedule, release_time) VALUES ($1,$2,$3,$4,$5)",
        fid,
        UUID(book_id),
        UUID(user_id),
        schedule,
        release_time,
    )
    return {"feed_id": str(fid), "rss_url": f"/api/v1/feeds/{fid}/rss"}


async def get_rss(feed_id: str) -> Response:
    feed = await fetch_one("SELECT * FROM podcast_feeds WHERE id = $1", UUID(feed_id))
    if not feed:
        return Response(content="Feed not found", status_code=404)

    book = await fetch_one("SELECT title FROM books WHERE id = $1", feed["book_id"])
    chapters = await fetch_all(
        """
        SELECT ac.* FROM audio_chapters ac JOIN book_files bf ON bf.id = ac.file_id
        WHERE bf.book_id = $1 ORDER BY ac.chapter_index
    """,
        feed["book_id"],
    )

    # Calculate release dates based on schedule
    start = feed["start_date"] or date.today()
    items = []
    for i, ch in enumerate(chapters):
        if feed["schedule"] == "daily":
            release = start + timedelta(days=i)
        elif feed["schedule"] == "weekdays":
            release = start + timedelta(days=i + (i // 5) * 2)
        else:
            release = start + timedelta(weeks=i)

        if release > date.today():
            break

        items.append(f"""<item>
  <title>{ch["title"] or f"Chapter {ch['chapter_index'] + 1}"}</title>
  <enclosure url="/api/v1/books/{feed["book_id"]}/audio/{ch["file_id"]}" type="audio/mpeg"/>
  <pubDate>{release.isoformat()}</pubDate>
</item>""")

    title = book["title"] if book else "Audiobook"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>{title}</title>
  <description>BrainyCat audiobook feed</description>
  {"".join(items)}
</channel></rss>"""
    return Response(content=xml, media_type="application/rss+xml")
