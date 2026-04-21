"""Library intelligence — quality, series, duplicates (multi-signal), author dedup, with caching."""

from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all, fetch_one

# In-memory cache for suggestions not yet acted upon
_cache: dict[str, Any] = {}


def _get_cached(key: str) -> Any:
    return _cache.get(key)


def _set_cached(key: str, value: Any) -> None:
    _cache[key] = value


def _clear_cached(key: str) -> None:
    _cache.pop(key, None)


async def quality_report() -> list[dict[str, Any]]:
    rows = await fetch_all("""
        SELECT b.id, b.title, bf.format, bf.bitrate, bf.has_chapters, bf.file_size
        FROM books b JOIN book_files bf ON bf.book_id = b.id ORDER BY b.title
    """)
    issues = []
    for r in rows:
        bi = []
        if r["format"] in ("mp3", "m4b", "m4a") and r["bitrate"] and r["bitrate"] < 64000:
            bi.append("low_bitrate")
        if r["format"] in ("mp3", "m4b") and not r["has_chapters"]:
            bi.append("no_chapters")
        if bi:
            issues.append({"id": str(r["id"]), "title": r["title"], "format": r["format"], "issues": bi})
    return issues


async def find_duplicates() -> list[dict[str, Any]]:
    """Multi-signal duplicate detection: title similarity + file size + author match."""
    cached = _get_cached("duplicates")
    if cached is not None:
        return cached

    # Get all books with their file sizes and authors
    rows = await fetch_all("""
        SELECT b.id, b.title, b.isbn,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT bf.file_size) FILTER (WHERE bf.file_size IS NOT NULL) as file_sizes,
               array_agg(DISTINCT bf.format) FILTER (WHERE bf.format IS NOT NULL) as formats,
               sum(bf.file_size) as total_size
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id
        LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN book_files bf ON bf.book_id = b.id
        GROUP BY b.id ORDER BY b.title
    """)

    books = [dict(r) for r in rows]
    dupes = []
    seen = set()

    for i, a in enumerate(books):
        for b in books[i + 1 :]:
            pair_key = f"{a['id']}:{b['id']}"
            if pair_key in seen:
                continue

            signals = []
            score = 0

            # 1) Title similarity (pg_trgm already computed, but we do it in Python for speed)
            title_a = _normalize(a["title"])
            title_b = _normalize(b["title"])
            if title_a == title_b:
                score += 50
                signals.append("exact_title")
            elif _jaccard(title_a.split(), title_b.split()) > 0.7:
                score += 35
                signals.append("similar_title")
            elif _jaccard(title_a.split(), title_b.split()) > 0.5:
                score += 20
                signals.append("partial_title")
            else:
                continue  # Skip if titles aren't even close

            # 2) Same author
            authors_a = {_normalize(x) for x in (a["authors"] or [])}
            authors_b = {_normalize(x) for x in (b["authors"] or [])}
            if authors_a & authors_b:
                score += 25
                signals.append("same_author")

            # 3) Same ISBN
            if a["isbn"] and b["isbn"] and a["isbn"] == b["isbn"]:
                score += 30
                signals.append("same_isbn")

            # 4) Similar file size (within 2%)
            if a["total_size"] and b["total_size"]:
                size_diff = abs(a["total_size"] - b["total_size"]) / max(a["total_size"], b["total_size"])
                if size_diff < 0.02:
                    score += 20
                    signals.append(f"similar_size ({size_diff:.1%} diff)")
                elif size_diff < 0.10:
                    score += 10
                    signals.append(f"close_size ({size_diff:.1%} diff)")

            # 5) Different format = likely same book in different formats (not a "duplicate" to delete, but to link)
            formats_a = set(a["formats"] or [])
            formats_b = set(b["formats"] or [])
            is_format_variant = formats_a != formats_b and score >= 40

            if score >= 40:
                seen.add(pair_key)
                dupes.append(
                    {
                        "book_a": str(a["id"]),
                        "title_a": a["title"],
                        "formats_a": a["formats"] or [],
                        "book_b": str(b["id"]),
                        "title_b": b["title"],
                        "formats_b": b["formats"] or [],
                        "score": score,
                        "signals": signals,
                        "is_format_variant": is_format_variant,
                        "action": "link" if is_format_variant else "merge",
                    }
                )

    dupes.sort(key=lambda d: d["score"], reverse=True)
    _set_cached("duplicates", dupes)
    return dupes


async def series_suggestions() -> list[dict[str, Any]]:
    """Detect potential series with confidence scores."""
    cached = _get_cached("series")
    if cached is not None:
        return cached

    suggestions = []

    # 1) Explicit series with gaps
    rows = await fetch_all("""
        SELECT s.id as series_id, s.name, array_agg(b.series_index ORDER BY b.series_index) as owned,
               array_agg(b.title ORDER BY b.series_index) as titles
        FROM books b JOIN books_series bs ON bs.book_id = b.id JOIN series s ON s.id = bs.series_id
        GROUP BY s.id, s.name
    """)
    for r in rows:
        owned = sorted({int(x) for x in r["owned"] if x})
        if owned:
            missing = sorted(set(range(1, max(owned) + 1)) - set(owned))
            if missing:
                suggestions.append(
                    {
                        "type": "series_gap",
                        "confidence": 95,
                        "series_id": str(r["series_id"]),
                        "series": r["name"],
                        "owned": owned,
                        "titles": r["titles"],
                        "missing": missing,
                        "action": "info",
                    }
                )

    # 2) Auto-detect by shared author + title patterns
    author_books = await fetch_all("""
        SELECT a.id as author_id, a.name as author,
               array_agg(json_build_object('id', b.id::text, 'title', b.title) ORDER BY b.title) as books
        FROM books b JOIN books_authors ba ON ba.book_id = b.id JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_series bs ON bs.book_id = b.id
        WHERE bs.book_id IS NULL
        GROUP BY a.id, a.name HAVING count(*) >= 2
    """)
    for ab in author_books:
        books = [_json.loads(b) if isinstance(b, str) else b for b in ab["books"]]
        if len(books) < 2:
            continue
        author_name = ab["author"]
        if (
            len(author_name) < 4
            or "/" in author_name
            or "\\" in author_name
            or author_name.lower() in {"unknown", "n/a", "user", "admin"}
            or not any(c.isupper() for c in author_name)
            or (author_name.isalnum() and len(author_name) < 10)
            or any(w in author_name.lower() for w in ["download", "onedrive", "dropbox", "targetstream", "technologies", "documents"])
        ):
            continue

        from collections import Counter

        words = Counter()
        stop = {
            "with",
            "from",
            "that",
            "this",
            "your",
            "have",
            "been",
            "will",
            "they",
            "their",
            "about",
            "guide",
            "book",
            "novel",
            "story",
            "edition",
            "volume",
        }
        for b in books:
            for w in b["title"].split():
                clean = w.lower().strip("'\",.!?():[]{}")
                if len(clean) > 3 and clean not in stop:
                    words[clean] += 1
        common = [w for w, c in words.items() if c >= 2]

        if common:
            confidence = min(90, 40 + len(common) * 15 + (10 if len(books) >= 3 else 0))
            series_name = " ".join(common[:3]).title()
            suggestions.append(
                {
                    "type": "create_series",
                    "confidence": confidence,
                    "series": series_name,
                    "author": ab["author"],
                    "author_id": str(ab["author_id"]),
                    "books": [{"id": b["id"], "title": b["title"], "index": i + 1} for i, b in enumerate(books)],
                    "action": "create_series",
                }
            )

    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    _set_cached("series", suggestions)
    return suggestions


async def author_suggestions() -> list[dict[str, Any]]:
    """Find similar author names that might be the same person."""
    cached = _get_cached("authors")
    if cached is not None:
        return cached

    rows = await fetch_all("""
        SELECT a.id, a.name, count(ba.book_id) as book_count
        FROM authors a LEFT JOIN books_authors ba ON ba.author_id = a.id
        GROUP BY a.id, a.name ORDER BY a.name
    """)
    suggestions = []
    authors = [dict(r) for r in rows]

    for i, a in enumerate(authors):
        for b in authors[i + 1 :]:
            norm_a, norm_b = _normalize(a["name"]), _normalize(b["name"])
            confidence = 0
            reason = ""

            if norm_a == norm_b:
                confidence = 95
                reason = "Same name (different formatting)"
            elif norm_a in norm_b or norm_b in norm_a:
                confidence = 70
                reason = "One name contains the other"
            else:
                parts_a = norm_a.split()
                parts_b = norm_b.split()
                if len(parts_a) >= 2 and len(parts_b) >= 2 and parts_a[-1] == parts_b[-1] and parts_a[0][0] == parts_b[0][0]:
                    confidence = 65
                    reason = "Same last name, matching first initial"

            if confidence >= 50:
                suggestions.append(
                    {
                        "type": "merge_authors",
                        "confidence": confidence,
                        "author_a": {"id": str(a["id"]), "name": a["name"], "books": a["book_count"]},
                        "author_b": {"id": str(b["id"]), "name": b["name"], "books": b["book_count"]},
                        "action": "merge_authors",
                        "reason": reason,
                    }
                )

    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    _set_cached("authors", suggestions)
    return suggestions


# ── Actions ──────────────────────────────────────────────────────────────


async def apply_create_series(series_name: str, book_ids: list[str]) -> dict[str, Any]:
    sid = uuid4()
    await execute("INSERT INTO series (id, name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING", sid, series_name)
    row = await fetch_one("SELECT id FROM series WHERE name = $1", series_name)
    actual_sid = row["id"] if row else sid
    for i, bid in enumerate(book_ids):
        await execute("INSERT INTO books_series (book_id, series_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", UUID(bid), actual_sid)
        await execute("UPDATE books SET series_index = $1 WHERE id = $2", float(i + 1), UUID(bid))
    _clear_cached("series")
    return {"ok": True, "series_id": str(actual_sid), "linked": len(book_ids)}


async def apply_merge_authors(keep_id: str, merge_id: str) -> dict[str, Any]:
    await execute(
        """
        UPDATE books_authors SET author_id = $1
        WHERE author_id = $2 AND book_id NOT IN (SELECT book_id FROM books_authors WHERE author_id = $1)
    """,
        UUID(keep_id),
        UUID(merge_id),
    )
    await execute("DELETE FROM books_authors WHERE author_id = $1", UUID(merge_id))
    merged = await fetch_one("SELECT name FROM authors WHERE id = $1", UUID(merge_id))
    await execute("DELETE FROM authors WHERE id = $1", UUID(merge_id))
    kept = await fetch_one("SELECT name FROM authors WHERE id = $1", UUID(keep_id))
    _clear_cached("authors")
    return {"ok": True, "kept": kept["name"] if kept else "", "merged": merged["name"] if merged else ""}


async def apply_link_duplicate(book_a_id: str, book_b_id: str, link_type: str = "edition") -> dict[str, Any]:
    """Link two duplicate books (different formats/editions of the same work)."""
    await execute(
        "INSERT INTO book_links (book_a_id, book_b_id, link_type) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        UUID(book_a_id),
        UUID(book_b_id),
        link_type,
    )
    _clear_cached("duplicates")
    return {"ok": True}


async def apply_batch(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply multiple actions in one go."""
    results = {"applied": 0, "errors": 0}
    for action in actions:
        try:
            if action["type"] == "create_series":
                await apply_create_series(action["series_name"], action["book_ids"])
            elif action["type"] == "merge_authors":
                await apply_merge_authors(action["keep_id"], action["merge_id"])
            elif action["type"] == "link_duplicate":
                await apply_link_duplicate(action["book_a_id"], action["book_b_id"], action.get("link_type", "edition"))
            results["applied"] += 1
        except Exception:
            results["errors"] += 1
    return results


# ── Helpers ──────────────────────────────────────────────────────────────


def _normalize(s: str) -> str:
    """Normalize a string for comparison: lowercase, collapse whitespace, handle Last/First."""
    import re

    s = s.lower().strip()
    # Handle "Last, First" → "first last" BEFORE stripping punctuation
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        s = " ".join(reversed(parts))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard similarity between two word lists."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
