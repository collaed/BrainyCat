"""Book summaries — getAbstract/Headway-style structured summaries via LLM.

Generates: executive summary, key takeaways, chapter summaries,
actionable insights. Cached per book. Best for non-fiction.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import httpx

from brainycat.config import settings
from brainycat.db import execute, fetch_one


async def generate_summary(book_id: str) -> dict[str, Any]:
    """Generate a structured summary for a non-fiction book."""
    # Check cache
    cached = await fetch_one(
        "SELECT extra_metadata->'summary' as summary FROM books WHERE id = $1",
        UUID(book_id),
    )
    if cached and cached["summary"]:
        try:
            return json.loads(cached["summary"]) if isinstance(cached["summary"], str) else cached["summary"]
        except (json.JSONDecodeError, TypeError):
            pass

    # Get book text
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub file"}

    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text(separator=" ", strip=True) + "\n"
            if len(text) > 30000:
                break
    except Exception as e:
        return {"error": str(e)[:100]}

    # Get book metadata
    meta = await fetch_one(
        "SELECT title, description FROM books WHERE id = $1",
        UUID(book_id),
    )
    title = meta["title"] if meta else "Unknown"

    prompt = f"""You are a professional book summarizer (like getAbstract or Blinkist).
Create a structured summary of this non-fiction book.

Book: {title}

Return as JSON:
{{
  "executive_summary": "2-3 sentence overview of the book's main thesis",
  "key_takeaways": ["5-7 bullet points of the most important ideas"],
  "chapter_summaries": [{{"chapter": "name/number", "summary": "2-3 sentences"}}],
  "actionable_insights": ["3-5 practical things the reader can do based on this book"],
  "who_should_read": "1 sentence describing the ideal reader",
  "reading_time_saved": "X hours → Y minutes"
}}

Book text (first 25K chars):
{text[:25000]}"""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": prompt}]},
                headers={"Authorization": f"Bearer {settings.intello_api_key}"},
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    summary = json.loads(m.group())
                    # Cache it
                    await execute(
                        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{summary}', $1::jsonb) WHERE id = $2",
                        json.dumps(summary),
                        UUID(book_id),
                    )
                    return summary
    except Exception:
        pass

    return {"error": "LLM unavailable — summary generation requires Intello"}
