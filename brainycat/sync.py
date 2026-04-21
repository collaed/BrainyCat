"""Text↔audio position sync mapping."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import fetch_all


async def get_sync_map(book_id: str) -> list[dict[str, Any]]:
    """Get sync map for a book."""
    rows = await fetch_all("SELECT * FROM sync_maps WHERE book_id = $1 ORDER BY chapter_index", UUID(book_id))
    return [dict(r) for r in rows]


async def translate_position(book_id: str, from_type: str, position: str) -> dict[str, Any]:
    """Translate a text position to audio timestamp or vice versa."""
    maps = await fetch_all("SELECT * FROM sync_maps WHERE book_id = $1 ORDER BY chapter_index", UUID(book_id))
    if not maps:
        return {"error": "No sync map available"}

    # Simple chapter-level mapping for now
    # Full word-level mapping would use the word timestamps in mappings JSONB
    for m in maps:
        words = m["mappings"] or []
        if from_type == "text" and words:
            # position is a percentage — find corresponding timestamp
            try:
                pct = float(position)
                idx = int(pct / 100 * len(words))
                idx = min(idx, len(words) - 1)
                return {"timestamp": words[idx]["start"], "chapter": m["chapter_index"]}
            except (ValueError, IndexError, KeyError):
                continue
        elif from_type == "audio" and words:
            try:
                ts = float(position)
                for w in words:
                    if w["start"] >= ts:
                        word_idx = words.index(w)
                        pct = (word_idx / len(words)) * 100
                        return {"percentage": pct, "chapter": m["chapter_index"]}
            except (ValueError, KeyError):
                continue

    return {"error": "Position not found in sync map"}
