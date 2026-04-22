"""Parallel edition diffing — show what changed between editions of a book.

Like git diff for books. Aligns chapters, then diffs paragraph by paragraph.
Useful for: revised novels, textbook editions, translation comparisons.
"""

from __future__ import annotations

import difflib
import re
from typing import Any
from uuid import UUID

from brainycat.db import fetch_one


async def diff_editions(book_id_a: str, book_id_b: str) -> dict[str, Any]:
    """Diff two editions of a book."""
    text_a = await _extract_text(book_id_a)
    text_b = await _extract_text(book_id_b)

    if not text_a or not text_b:
        return {"error": "could not extract text from one or both books"}

    paras_a = _split_paragraphs(text_a)
    paras_b = _split_paragraphs(text_b)

    # Use SequenceMatcher for paragraph-level alignment
    matcher = difflib.SequenceMatcher(None, paras_a, paras_b)
    changes: list[dict[str, Any]] = []
    stats = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            stats["unchanged"] += i2 - i1
        elif tag == "replace":
            stats["changed"] += max(i2 - i1, j2 - j1)
            for k in range(max(i2 - i1, j2 - j1)):
                old = paras_a[i1 + k] if i1 + k < i2 else ""
                new = paras_b[j1 + k] if j1 + k < j2 else ""
                if old != new:
                    changes.append({"type": "changed", "old": old[:300], "new": new[:300], "position": i1 + k})
        elif tag == "insert":
            stats["added"] += j2 - j1
            for k in range(j1, j2):
                changes.append({"type": "added", "text": paras_b[k][:300], "position": k})
        elif tag == "delete":
            stats["removed"] += i2 - i1
            for k in range(i1, i2):
                changes.append({"type": "removed", "text": paras_a[k][:300], "position": k})

    similarity = matcher.ratio()

    return {
        "similarity": round(similarity * 100, 1),
        "stats": stats,
        "total_paragraphs_a": len(paras_a),
        "total_paragraphs_b": len(paras_b),
        "changes": changes[:100],  # Cap at 100 changes
    }


async def _extract_text(book_id: str) -> str | None:
    """Extract text from a book."""
    row = await fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return None
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text(separator="\n", strip=True) + "\n"
        return text
    except Exception:
        return None


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs, filtering empty ones."""
    paras = re.split(r"\n\s*\n|\n", text)
    return [p.strip() for p in paras if len(p.strip()) > 20]
