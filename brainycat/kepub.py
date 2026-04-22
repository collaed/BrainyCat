"""Kobo KEPUB output — convert EPUB to Kobo's enhanced EPUB format.

KEPUB is EPUB with Kobo-specific additions:
- kobo spans around each paragraph/sentence for reading stats
- content.opf modifications for Kobo features
- Kobo-specific CSS classes
"""

from __future__ import annotations

import os
import re
import zipfile
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one


async def epub_to_kepub(book_id: str) -> dict[str, Any]:
    """Convert an EPUB to Kobo KEPUB format."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub file"}

    src = row["file_path"]
    out_path = src.replace(".epub", ".kepub.epub")

    try:
        with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(out_path, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if item.filename.endswith((".xhtml", ".html", ".htm")):
                    # Add Kobo spans around paragraphs
                    text = data.decode("utf-8", errors="replace")
                    text = _add_kobo_spans(text)
                    data = text.encode("utf-8")

                zout.writestr(item, data)

        await execute(
            "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
            uuid4(),
            UUID(book_id),
            "kepub",
            out_path,
            os.path.basename(out_path),
        )
        return {"ok": True, "path": out_path}

    except Exception as e:
        return {"error": str(e)[:200]}


def _add_kobo_spans(html: str) -> str:
    """Wrap paragraphs in Kobo tracking spans."""
    counter = [0]

    def _wrap(match: re.Match) -> str:
        content = match.group(1)
        counter[0] += 1
        span_id = f"kobo.{counter[0]}.1"
        return f'<p><span class="koboSpan" id="{span_id}">{content}</span></p>'

    return re.sub(r"<p[^>]*>(.*?)</p>", _wrap, html, flags=re.DOTALL)
