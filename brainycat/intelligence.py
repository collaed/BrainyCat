"""Library intelligence — quality analysis, series gaps, duplicates, author dedup, actionable suggestions."""

from __future__ import annotations

import json as _json
from typing import Any
from uuid import uuid4

from brainycat.db import execute, fetch_all, fetch_one


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


async def series_suggestions() -> list[dict[str, Any]]:
    """Detect potential series with confidence scores and actionable suggestions."""
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
                        "message": f"Missing #{', #'.join(map(str, missing))} in {r['name']}",
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
        # Skip garbage author names
        author_name = ab["author"]
        if (
            len(author_name) < 4
            or "/" in author_name
            or "\\" in author_name
            or author_name.lower() in {"unknown", "n/a", "user", "admin"}
            or not any(c.isupper() for c in author_name)  # no capitals = not a real name
            or any(
                w in author_name.lower() for w in ["download", "onedrive", "dropbox", "targetstream", "technologies", "documents"]
            )  # path fragments
            or (author_name.isalnum() and len(author_name) < 10)  # short single-word = username
        ):
            continue

        # Common significant words in titles
        from collections import Counter

        words = Counter()
        for b in books:
            for w in b["title"].split():
                clean = w.lower().strip("'\",.!?():")
                if len(clean) > 3 and clean not in {
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
                }:
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
                    "message": f"Create series '{series_name}' with {len(books)} books?",
                }
            )

    # Sort by confidence descending
    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    return suggestions


async def author_suggestions() -> list[dict[str, Any]]:
    """Find similar author names that might be the same person."""
    rows = await fetch_all("""
        SELECT a.id, a.name, count(ba.book_id) as book_count
        FROM authors a LEFT JOIN books_authors ba ON ba.author_id = a.id
        GROUP BY a.id, a.name ORDER BY a.name
    """)
    suggestions = []
    authors = [dict(r) for r in rows]

    for i, a in enumerate(authors):
        for b in authors[i + 1 :]:
            name_a, name_b = a["name"].lower(), b["name"].lower()
            # Check similarity
            sim = await fetch_one("SELECT similarity($1, $2) as sim", a["name"], b["name"])
            sim_score = float(sim["sim"]) if sim else 0

            confidence = 0
            reason = ""

            # High similarity
            if sim_score > 0.6:
                confidence = int(sim_score * 100)
                reason = f"Name similarity: {confidence}%"

            # One name contains the other (abbreviation)
            elif name_a in name_b or name_b in name_a:
                confidence = 70
                reason = "One name contains the other"

            # Same last name + first initial match
            else:
                parts_a = name_a.replace(",", " ").split()
                parts_b = name_b.replace(",", " ").split()
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
                        "message": f"Merge '{a['name']}' and '{b['name']}'? ({reason})",
                    }
                )

    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    return suggestions


async def apply_create_series(series_name: str, book_ids: list[str]) -> dict[str, Any]:
    """Create a series and link books to it."""
    sid = uuid4()
    await execute("INSERT INTO series (id, name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING", sid, series_name)
    row = await fetch_one("SELECT id FROM series WHERE name = $1", series_name)
    actual_sid = row["id"] if row else sid
    for i, bid in enumerate(book_ids):
        from uuid import UUID

        await execute("INSERT INTO books_series (book_id, series_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", UUID(bid), actual_sid)
        await execute("UPDATE books SET series_index = $1 WHERE id = $2", float(i + 1), UUID(bid))
    return {"ok": True, "series_id": str(actual_sid), "linked": len(book_ids)}


async def apply_merge_authors(keep_id: str, merge_id: str) -> dict[str, Any]:
    """Merge two authors — move all books from merge_id to keep_id, then delete merge_id."""
    from uuid import UUID

    # Move book links
    await execute(
        """
        UPDATE books_authors SET author_id = $1
        WHERE author_id = $2 AND book_id NOT IN (SELECT book_id FROM books_authors WHERE author_id = $1)
    """,
        UUID(keep_id),
        UUID(merge_id),
    )
    # Delete remaining (duplicates)
    await execute("DELETE FROM books_authors WHERE author_id = $1", UUID(merge_id))
    # Delete the merged author
    merged = await fetch_one("SELECT name FROM authors WHERE id = $1", UUID(merge_id))
    await execute("DELETE FROM authors WHERE id = $1", UUID(merge_id))
    kept = await fetch_one("SELECT name FROM authors WHERE id = $1", UUID(keep_id))
    return {"ok": True, "kept": kept["name"] if kept else "", "merged": merged["name"] if merged else ""}


async def find_duplicates() -> list[dict[str, Any]]:
    rows = await fetch_all("""
        SELECT a.id as id_a, a.title as title_a, b.id as id_b, b.title as title_b,
               similarity(a.title, b.title) as sim
        FROM books a, books b
        WHERE a.id < b.id AND similarity(a.title, b.title) > 0.4
        ORDER BY sim DESC LIMIT 50
    """)
    return [
        {
            "book_a": str(r["id_a"]),
            "title_a": r["title_a"],
            "book_b": str(r["id_b"]),
            "title_b": r["title_b"],
            "similarity": round(float(r["sim"]) * 100),
        }
        for r in rows
    ]
