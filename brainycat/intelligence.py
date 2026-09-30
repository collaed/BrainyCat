"""Library intelligence — quality, series, duplicates (multi-signal), author dedup, with caching."""

from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.title_confidence import is_unresolved_title

# In-memory cache for suggestions not yet acted upon
_cache: dict[str, Any] = {}


def _get_cached(key: str) -> Any:
    """Return a cached suggestion list, or None if not cached. Internal helper used by this module."""
    return _cache.get(key)


def _set_cached(key: str, value: Any) -> None:
    """Store a suggestion list in the in-memory cache. Internal helper used by this module."""
    _cache[key] = value


def _clear_cached(key: str) -> None:
    """Invalidate a cached suggestion list, e.g. after an action changes the underlying data."""
    _cache.pop(key, None)


async def quality_report() -> list[dict[str, Any]]:
    """Flag books with unresolved titles, low bitrate, or missing chapters.

    Called by GET /api/v1/intelligence/quality (routes/enrichment.py), used by
    intel-quality.html and fix-library.html.
    """
    rows = await fetch_all("""
        SELECT b.id, b.title, bf.format, bf.bitrate, bf.has_chapters, bf.file_size
        FROM books b JOIN book_files bf ON bf.book_id = b.id ORDER BY b.title
    """)
    issues = []
    for r in rows:
        bi = []
        if is_unresolved_title(r["title"]):
            bi.append("unresolved_title")
        if r["format"] in ("mp3", "m4b", "m4a") and r["bitrate"] and r["bitrate"] < 64000:
            bi.append("low_bitrate")
        if r["format"] in ("mp3", "m4b") and not r["has_chapters"]:
            bi.append("no_chapters")
        if bi:
            issues.append({"id": str(r["id"]), "title": r["title"], "format": r["format"], "issues": bi})
    issues.sort(key=lambda i: 0 if "unresolved_title" in i["issues"] else 1)
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
    # Precompute once per book, not per pair — this loop is O(n^2) and _normalize() does several
    # regex substitutions, so recomputing it ~2x per pair (instead of once per book) turns a few
    # thousand books into tens of millions of redundant regex calls.
    for bk in books:
        bk["_norm_title"] = _normalize(bk["title"])
        bk["_norm_authors"] = {_normalize(x) for x in (bk["authors"] or [])}
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
            title_a = a["_norm_title"]
            title_b = b["_norm_title"]
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
            if a["_norm_authors"] & b["_norm_authors"]:
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

            # Filter out series entries: same author + titles differ by number/volume
            if score >= 40 and "same_author" in signals:
                import re

                # Strip numbers and check if base titles are identical
                base_a = re.sub(r"\d+|#\d+|vol\.?\s*\d+|book\s*\d+|part\s*\d+", "", title_a).strip()
                base_b = re.sub(r"\d+|#\d+|vol\.?\s*\d+|book\s*\d+|part\s*\d+", "", title_b).strip()
                if (
                    base_a != base_b
                    and _jaccard(base_a.split(), base_b.split()) < 0.8
                    and "exact_title" not in signals
                    and "same_isbn" not in signals
                ):
                    continue  # Likely a series, not duplicate

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

        # Collapse near-duplicate titles within this author's group first — the same book
        # re-uploaded/re-sourced under slightly different filenames is not a second volume of a
        # series (this is find_duplicates()'s anti-series filter in reverse: an anti-duplicate
        # filter here, since otherwise a pile of dupes reads as "N books that share words").
        distinct: list[dict[str, Any]] = []
        for b in books:
            nb = _normalize(b["title"])
            if any(nb == _normalize(d["title"]) or _jaccard(nb.split(), _normalize(d["title"]).split()) > 0.7 for d in distinct):
                continue
            distinct.append(b)
        books = distinct

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
    """Create (or reuse) a series and attach the given books to it in order.

    Called by POST /api/v1/intelligence/apply-series (routes/enrichment.py, used by
    intel-series.html) and internally by apply_batch().
    """
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
    """Reassign one author's books to another and delete the merged author record.

    Called by POST /api/v1/intelligence/merge-authors (routes/enrichment.py, used by
    intel-authors.html) and internally by apply_batch().
    """
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
    """Normalize a string for comparison: lowercase, collapse whitespace, handle Last/First.

    Also strips a few trailing noise patterns that are common on raw scraped titles but never
    carry book identity — a scrape-site suffix, a "(YYYY[, Publisher])" tag, or a "(Nth Edition)"/
    "(Language Edition)" imprint note — so that two copies of the same book sourced differently
    (one with the tag, one without, or with a different tag) still normalize to the same string.
    Deliberately does NOT touch bracket/paren content in general, since series/volume markers like
    "(Book 2)"/"[Vol. 3]" often live there and must keep distinguishing different books.
    """
    import re

    s = s.lower().strip()
    s = re.sub(r"[\-\u2013\u2014]\s*libgen\.\w+(\(\d+\))?\s*$", "", s)
    s = re.sub(r"[\-\u2013\u2014]{0,2}\s*anna.?s archive\s*$", "", s)
    s = re.sub(r"\[?z-?library\]?\s*$", "", s)
    s = re.sub(r"\((?:19|20)\d{2}(?:,[^)]*)?\)\s*$", "", s)
    s = re.sub(r"\((?:\w+\s+)?edition\)\s*$", "", s, flags=re.IGNORECASE)
    s = s.strip()
    # Handle "Last, First" → "first last" BEFORE stripping punctuation
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        s = " ".join(reversed(parts))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _soundex(name: str) -> str:
    """American Soundex — phonetic matching for misspellings."""
    name = name.upper().strip()
    if not name:
        return ""
    coded = name[0]
    mapping = {"BFPV": "1", "CGJKQSXZ": "2", "DT": "3", "L": "4", "MN": "5", "R": "6"}
    prev = ""
    for ch in name[1:]:
        code = ""
        for chars, digit in mapping.items():
            if ch in chars:
                code = digit
                break
        if code and code != prev:
            coded += code
        prev = code
        if len(coded) >= 4:
            break
    return coded.ljust(4, "0")


def _jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard similarity between two word lists."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
