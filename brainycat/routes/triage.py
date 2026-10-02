"""Triage queue — high-impact human decisions for data quality."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from brainycat.auth import get_current_user
from brainycat.db import execute, fetch_all, fetch_one

router = APIRouter(prefix="/api/v1/triage", tags=["triage"])

_MARK_VERIFIED_SQL = (
    "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), "
    "'{human_verified}', 'true'::jsonb) WHERE id = $1"
)


@router.get("/next")
async def next_item(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get the next highest-impact item for human review."""

    # Priority 1: Low-confidence title matches (0.4-0.6)
    row = await fetch_one("""
        SELECT b.id, b.title, b.isbn, b.cover_path, b.original_filename,
               b.extra_metadata->'local_title_tried' as match_info,
               b.extra_metadata->'all_isbns' as all_isbns
        FROM books b
        WHERE (b.extra_metadata->'local_title_tried'->>'confidence')::float < 0.7
          AND b.extra_metadata->'local_title_tried'->>'confidence' IS NOT NULL
          AND b.isbn IS NOT NULL
          AND NOT (b.extra_metadata ? 'human_verified')
        ORDER BY (b.extra_metadata->'local_title_tried'->>'confidence')::float ASC
        LIMIT 1
    """)
    if row:
        ol_info = await _get_ol_info(row["isbn"])
        return {"type": "title_match", "book": _book_dict(row), "ol": ol_info}

    # Priority 2: Multi-ISBN (system picked one, alternatives available)
    row = await fetch_one("""
        SELECT b.id, b.title, b.isbn, b.cover_path, b.original_filename,
               b.extra_metadata->'all_isbns' as all_isbns
        FROM books b
        WHERE jsonb_array_length(COALESCE(b.extra_metadata->'all_isbns', '[]'::jsonb)) > 2
          AND NOT (b.extra_metadata ? 'human_verified')
          AND b.isbn IS NOT NULL
        ORDER BY jsonb_array_length(b.extra_metadata->'all_isbns') DESC
        LIMIT 1
    """)
    if row:
        ol_info = await _get_ol_info(row["isbn"])
        alts = []
        for alt in (json.loads(row["all_isbns"]) if row["all_isbns"] else []):
            if alt["isbn"] != row["isbn"]:
                alts.append({**alt, "ol": await _get_ol_info(alt["isbn"])})
        return {"type": "multi_isbn", "book": _book_dict(row), "ol": ol_info, "alternatives": alts[:5]}

    # Priority 3: Dirty titles
    row = await fetch_one("""
        SELECT b.id, b.title, b.isbn, b.cover_path, b.original_filename
        FROM books b
        WHERE (b.title LIKE 'Microsoft Word%' OR b.title LIKE '%.p65' OR b.title LIKE '%.qxp%'
               OR b.title LIKE '%libgen%' OR b.title LIKE '%freemagazines%')
          AND NOT (b.extra_metadata ? 'title_cleaned')
        LIMIT 1
    """)
    if row:
        suggested = _suggest_title(row["title"], row["original_filename"])
        return {"type": "dirty_title", "book": _book_dict(row), "suggested_title": suggested}

    # Priority 4: Validation mismatches
    row = await fetch_one("""
        SELECT b.id, b.title, b.isbn, b.cover_path, b.original_filename,
               b.extra_metadata->'validation' as validation
        FROM books b
        WHERE b.extra_metadata->'validation'->>'confidence' = 'low'
          AND NOT (b.extra_metadata ? 'human_verified')
          AND b.isbn IS NOT NULL
        ORDER BY b.quality_score DESC
        LIMIT 1
    """)
    if row:
        ol_info = await _get_ol_info(row["isbn"])
        return {"type": "validation_mismatch", "book": _book_dict(row), "ol": ol_info, "flags": json.loads(row["validation"]) if row["validation"] else {}}

    # Priority 5: High-confidence bulk confirm
    rows = await fetch_all("""
        SELECT b.id, b.title, b.isbn, b.cover_path,
               (b.extra_metadata->>'confidence_score')::int as confidence
        FROM books b
        WHERE (b.extra_metadata->>'confidence_score')::int >= 80
          AND NOT (b.extra_metadata ? 'human_verified')
        ORDER BY (b.extra_metadata->>'confidence_score')::int DESC
        LIMIT 10
    """)
    if rows:
        return {"type": "bulk_confirm", "books": [_book_dict(r) for r in rows]}

    return {"type": "empty", "message": "Nothing to review!"}


@router.post("/decide")
async def decide(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Apply a triage decision."""
    book_id = UUID(body["book_id"])
    action = body["action"]  # "confirm", "reject", "fix"

    if action == "confirm":
        await execute(
            _MARK_VERIFIED_SQL,
            book_id,
        )
        return {"ok": True, "action": "confirmed"}

    elif action == "reject":
        # Remove the bad ISBN, clear title match, put back in pool
        await execute(
            "UPDATE books SET isbn = NULL, extra_metadata = extra_metadata - 'local_title_tried' - 'local_enriched' - 'confidence_score' WHERE id = $1",
            book_id,
        )
        return {"ok": True, "action": "rejected"}

    elif action == "fix_isbn":
        new_isbn = body.get("isbn")
        if new_isbn:
            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", new_isbn, book_id)
            await execute(
                _MARK_VERIFIED_SQL,
                book_id,
            )
        return {"ok": True, "action": "isbn_fixed"}

    elif action == "fix_title":
        new_title = body.get("title")
        if new_title:
            await execute("UPDATE books SET title = $1, updated_at = now() WHERE id = $2", new_title, book_id)
            await execute(
                "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{title_cleaned}', 'true'::jsonb) WHERE id = $1",
                book_id,
            )
        return {"ok": True, "action": "title_fixed"}

    elif action == "bulk_confirm":
        book_ids = body.get("book_ids", [])
        for bid in book_ids:
            await execute(
                _MARK_VERIFIED_SQL,
                UUID(bid),
            )
        return {"ok": True, "action": "bulk_confirmed", "count": len(book_ids)}

    return {"ok": False, "error": "unknown action"}


@router.get("/stats")
async def triage_stats(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Queue sizes for each triage category."""
    low_conf = await fetch_one("SELECT count(*) as n FROM books WHERE (extra_metadata->'local_title_tried'->>'confidence')::float < 0.7 AND extra_metadata->'local_title_tried'->>'confidence' IS NOT NULL AND isbn IS NOT NULL AND NOT (extra_metadata ? 'human_verified')")
    multi = await fetch_one("SELECT count(*) as n FROM books WHERE jsonb_array_length(COALESCE(extra_metadata->'all_isbns','[]'::jsonb)) > 2 AND NOT (extra_metadata ? 'human_verified') AND isbn IS NOT NULL")
    dirty = await fetch_one("SELECT count(*) as n FROM books WHERE (title LIKE 'Microsoft Word%' OR title LIKE '%.p65' OR title LIKE '%.qxp%' OR title LIKE '%libgen%' OR title LIKE '%freemagazines%') AND NOT (extra_metadata ? 'title_cleaned')")
    valid = await fetch_one("SELECT count(*) as n FROM books WHERE extra_metadata->'validation'->>'confidence' = 'low' AND NOT (extra_metadata ? 'human_verified') AND isbn IS NOT NULL")
    bulk = await fetch_one("SELECT count(*) as n FROM books WHERE (extra_metadata->>'confidence_score')::int >= 80 AND NOT (extra_metadata ? 'human_verified')")
    return {
        "title_matches": low_conf["n"] if low_conf else 0,
        "multi_isbn": multi["n"] if multi else 0,
        "dirty_titles": dirty["n"] if dirty else 0,
        "validation": valid["n"] if valid else 0,
        "bulk_confirm": bulk["n"] if bulk else 0,
    }


def _book_dict(row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "isbn": row.get("isbn"),
        "cover": row.get("cover_path"),
        "filename": row.get("original_filename"),
        "match_info": json.loads(row["match_info"]) if row.get("match_info") else None,
        "all_isbns": json.loads(row["all_isbns"]) if row.get("all_isbns") else None,
        "confidence": row.get("confidence"),
    }


async def _get_ol_info(isbn: str) -> dict[str, Any] | None:
    if not isbn:
        return None
    try:
        from brainycat.ol_local import lookup_isbn
        # lookup_isbn is a blocking SQLite query: keep it off the event loop.
        r = await asyncio.to_thread(lookup_isbn, isbn.strip().replace("-", ""))
        if r:
            return {"title": r.get("title"), "authors": r.get("authors"), "year": r.get("year"), "publisher": r.get("publisher")}
    except Exception:
        pass
    return None


def _suggest_title(title: str, filename: str | None) -> str:
    """Suggest a cleaned title from the dirty one or the filename."""
    import re
    # Try to extract from filename first
    if filename:
        name = filename.rsplit(".", 1)[0]  # remove extension
        # Remove common patterns
        name = name.removeprefix("Microsoft Word - ")
        name = re.split(r"-\s*(?:libgen\.li|z-lib|epubBooks)", name, maxsplit=1)[0].rstrip()
        name = name.replace("_", " ")
        if len(name) > 5:
            return name.strip()
    # Clean the title itself
    clean = title.removeprefix("Microsoft Word - ")
    clean = re.sub(r"\.p65$|\.qxp.*$", "", clean)
    clean = re.split(r"-\s*(?:libgen\.li|freemagazines)", clean, maxsplit=1)[0].rstrip()
    return clean.strip()
