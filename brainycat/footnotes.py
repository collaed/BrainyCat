"""Contextual Footnotes — LLM-generated footnotes for historical/cultural references.

Pre-generates footnotes for a chapter when the reader opens it.
Cached per book+chapter. Displayed as hover tooltips in the reader.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client


async def generate_footnotes(book_id: str, chapter_text: str, chapter_idx: int = 0) -> list[dict[str, Any]]:
    """Generate contextual footnotes for a chapter via LLM."""
    # Check cache
    cached = await fetch_one(
        "SELECT footnotes FROM chapter_footnotes WHERE book_id = $1 AND chapter_idx = $2",
        UUID(book_id),
        chapter_idx,
    )
    if cached and cached["footnotes"]:
        return json.loads(cached["footnotes"]) if isinstance(cached["footnotes"], str) else cached["footnotes"]

    # Truncate to fit LLM context
    text = chapter_text[:6000]
    prompt = f"""Identify historical, cultural, literary, or geographical references in this text that a reader might not know. For each, provide:
- The exact phrase from the text
- A brief explanation (1-2 sentences)

Return as JSON array: [{{"phrase": "...", "note": "..."}}]
Only include references that genuinely need explanation. Skip obvious ones.

Text:
{text}"""

    footnotes: list[dict[str, Any]] = []
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {settings.intello_api_key}"},
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"\[.*\]", content, re.DOTALL)
            if m:
                footnotes = json.loads(m.group())
    except Exception:
        pass

    # Cache
    if footnotes:
        await execute(
            """
            INSERT INTO chapter_footnotes (book_id, chapter_idx, footnotes)
            VALUES ($1, $2, $3)
            ON CONFLICT (book_id, chapter_idx) DO UPDATE SET footnotes = $3
        """,
            UUID(book_id),
            chapter_idx,
            json.dumps(footnotes),
        )

    return footnotes
