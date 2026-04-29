"""Magic Shelves — dynamic, rules-based book views (inspired by CWA)."""

from __future__ import annotations

from typing import Any

from brainycat.db import fetch_all, fetch_one

# Pre-built shelf templates
BUILTIN_SHELVES = [
    {"id": "recent", "name": "📥 Recently Added", "query": "ORDER BY b.created_at DESC LIMIT 50", "icon": "📥"},
    {"id": "reading", "name": "📖 Currently Reading", "query": "JOIN reading_progress rp ON rp.book_id = b.id WHERE rp.percentage > 0 AND rp.percentage < 100 ORDER BY rp.updated_at DESC", "icon": "📖"},
    {"id": "unread", "name": "🆕 Unread", "query": "WHERE NOT EXISTS (SELECT 1 FROM reading_progress rp WHERE rp.book_id = b.id AND rp.percentage > 0) ORDER BY b.created_at DESC LIMIT 100", "icon": "🆕"},
    {"id": "no_cover", "name": "🖼️ Missing Cover", "query": "WHERE b.cover_path IS NULL", "icon": "🖼️"},
    {"id": "no_isbn", "name": "🔢 Missing ISBN", "query": "WHERE b.isbn IS NULL", "icon": "🔢"},
    {"id": "low_quality", "name": "⚠️ Low Quality (<50)", "query": "WHERE b.quality_score < 50", "icon": "⚠️"},
    {"id": "top_rated", "name": "⭐ Highest Quality", "query": "WHERE b.quality_score >= 85 ORDER BY b.quality_score DESC", "icon": "⭐"},
    {"id": "audiobooks", "name": "🎧 Audiobooks", "query": "JOIN book_files bf ON bf.book_id = b.id WHERE bf.format IN ('mp3','m4b','m4a','flac')", "icon": "🎧"},
    {"id": "french", "name": "🇫🇷 French", "query": "WHERE b.language = 'fra'", "icon": "🇫🇷"},
    {"id": "german", "name": "🇩🇪 German", "query": "WHERE b.language = 'deu'", "icon": "🇩🇪"},
    {"id": "large", "name": "📚 500+ Pages", "query": "WHERE b.page_count > 500 ORDER BY b.page_count DESC", "icon": "📚"},
    {"id": "pamphlets", "name": "📄 Short (<50 pages)", "query": "WHERE b.page_count > 0 AND b.page_count < 50", "icon": "📄"},
]


async def get_shelves() -> list[dict[str, Any]]:
    """Get all shelves with book counts."""
    shelves = []
    for s in BUILTIN_SHELVES:
        try:
            row = await fetch_one(f"SELECT count(*) as cnt FROM books b {s['query'].split('ORDER')[0].split('LIMIT')[0]}")
            count = row["cnt"] if row else 0
        except Exception:
            count = 0
        shelves.append({**s, "count": count})
    return shelves


async def get_shelf_books(shelf_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get books for a specific shelf."""
    shelf = next((s for s in BUILTIN_SHELVES if s["id"] == shelf_id), None)
    if not shelf:
        return []

    query = shelf["query"]
    # Ensure LIMIT/OFFSET
    if "LIMIT" not in query:
        query += f" LIMIT {limit} OFFSET {offset}"

    rows = await fetch_all(
        f"SELECT b.id, b.title, b.isbn, b.cover_path, b.quality_score, b.language FROM books b {query}"
    )
    return [dict(r) for r in rows]
