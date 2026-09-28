"""Title cleanup — background process to fix dirty titles.

Runs as part of the scheduler. Three strategies:
1. ISBN-from-filename: extract ISBNs embedded in filenames
2. API title lookup: fetch canonical title from Google Books by ISBN
3. Filename cleanup: strip libgen.li, Anna's Archive, author prefixes
"""

from __future__ import annotations

import html
import re
from typing import Any

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client
from brainycat.isbn import _clean_isbn
from brainycat.rate_limit import rate_limiter
from brainycat.title_parse import parse_title

_ENTITY_RE = re.compile(r"&#\d+;|&#x[0-9a-fA-F]+;|&[a-zA-Z]+;")


async def decode_html_entities(limit: int = 50) -> dict[str, int]:
    """Fix titles/descriptions that still contain raw HTML entities (e.g. 'Dummies&#174;' instead
    of 'Dummies®') — leaks from a source that returned HTML-escaped text that never got decoded."""
    rows = await fetch_all(
        "SELECT id, title, description FROM books WHERE title ~ $1 OR description ~ $1 LIMIT $2",
        _ENTITY_RE.pattern,
        limit,
    )
    fixed = 0
    for r in rows:
        new_title = html.unescape(r["title"]) if r["title"] else r["title"]
        new_desc = html.unescape(r["description"]) if r["description"] else r["description"]
        if new_title != r["title"] or new_desc != r["description"]:
            await execute("UPDATE books SET title = $1, description = $2 WHERE id = $3", new_title, new_desc, r["id"])
            fixed += 1
    return {"fixed": fixed, "checked": len(rows)}


async def apply_local_title_parse(limit: int = 30) -> dict[str, int]:
    """Parse structured metadata (title/author/isbn/publisher) directly out of Anna's Archive /
    libgen.li style filename-derived titles — no external lookup, no rate limit, and it works even
    for titles enrichment could never search for (e.g. a bare content-hash title with no words at
    all). See brainycat.title_parse for the actual parsing logic."""
    rows = await fetch_all(
        """
        SELECT id, title FROM books
        WHERE identity_status = 'auto'
          AND NOT (extra_metadata ? 'title_parsed')
          AND (title ~ '^[0-9a-f]{8} ' OR title ILIKE '%Anna%Archive%' OR title ILIKE '%libgen%' OR length(title) > 35)
        LIMIT $1
        """,
        limit,
    )
    applied = 0
    for r in rows:
        parsed = parse_title(r["title"])
        if parsed.confidence in ("high", "medium") and parsed.title and parsed.title != r["title"]:
            sets, vals = ["title = $1"], [parsed.title]
            idx = 2
            if parsed.isbn:
                sets.append(f"isbn = COALESCE(isbn, ${idx})")
                vals.append(parsed.isbn)
                idx += 1
            extra: dict[str, Any] = {"title_parsed": True}
            if parsed.publisher:
                extra["publisher_guess"] = parsed.publisher
            if parsed.year:
                extra["year_guess"] = parsed.year
            import json as _json

            sets.append(f"extra_metadata = COALESCE(extra_metadata, '{{}}'::jsonb) || ${idx}::jsonb")
            vals.append(_json.dumps(extra))
            idx += 1
            vals.append(r["id"])
            await execute(f"UPDATE books SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)

            from brainycat.metadata_audit import record_change

            await record_change(str(r["id"]), "title", r["title"], parsed.title, "local_filename_parse")
            if parsed.isbn:
                await record_change(str(r["id"]), "isbn", None, parsed.isbn, "local_filename_parse")

            if parsed.author:
                from brainycat.author_names import split_authors

                has_author = await fetch_one("SELECT 1 FROM books_authors WHERE book_id = $1 LIMIT 1", r["id"])
                if not has_author:
                    for name in split_authors(parsed.author):
                        await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", name)
                        author_row = await fetch_one("SELECT id FROM authors WHERE name = $1", name)
                        if author_row:
                            await execute(
                                "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                r["id"],
                                author_row["id"],
                            )

            # A much cleaner title/isbn is new evidence — clear stale enrichment attempts so the
            # next background pass retries with it instead of waiting out the old backoff.
            await execute("DELETE FROM enrichment_log WHERE book_id = $1", r["id"])
            applied += 1
        else:
            await execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || '{\"title_parsed\": true}'::jsonb WHERE id = $1",
                r["id"],
            )
    return {"applied": applied, "checked": len(rows)}


async def extract_isbn_from_title(limit: int = 20) -> dict[str, int]:
    """Find ISBNs embedded in book titles (e.g. 'isbn 9781118146415')."""
    import re

    rows = await fetch_all(
        """
        SELECT id, title FROM books
        WHERE isbn IS NULL AND (title ~* '978[0-9-]{10,}' OR title ~* 'isbn')
        LIMIT $1
    """,
        limit,
    )
    found = 0
    for r in rows:
        for m in re.finditer(r"97[89][\d-]{10,17}", r["title"]):
            isbn = _clean_isbn(m.group())
            if isbn:
                await execute("UPDATE books SET isbn = $1 WHERE id = $2 AND isbn IS NULL", isbn, r["id"])
                found += 1
                break
    return {"found": found, "checked": len(rows)}


async def extract_isbn_from_filename(limit: int = 20) -> dict[str, int]:
    """Find ISBNs embedded in filenames and store them."""
    rows = await fetch_all(
        """
        SELECT bf.book_id, bf.file_name FROM book_files bf
        JOIN books b ON b.id = bf.book_id
        WHERE b.isbn IS NULL AND bf.file_name IS NOT NULL
        LIMIT $1
    """,
        limit,
    )

    found = 0
    for r in rows:
        fname = r["file_name"] or ""
        # Look for ISBN-13 or ISBN-10 in filename
        for m in re.finditer(r"97[89][\d-]{10,17}", fname):
            isbn = _clean_isbn(m.group())
            if isbn:
                await execute("UPDATE books SET isbn = $1 WHERE id = $2 AND isbn IS NULL", isbn, r["book_id"])
                found += 1
                break
        else:
            # Try ISBN-10
            for m in re.finditer(r"\b\d{9}[\dXx]\b", fname):
                isbn = _clean_isbn(m.group())
                if isbn:
                    await execute("UPDATE books SET isbn = $1 WHERE id = $2 AND isbn IS NULL", isbn, r["book_id"])
                    found += 1
                    break
    return {"found": found, "checked": len(rows)}


async def fix_titles_from_api(limit: int = 10) -> dict[str, int]:
    """Fetch canonical titles from Google Books for books with ISBNs and messy titles."""
    # No "does this look messy" heuristic — any book with a real ISBN has an authoritative title
    # available, and `title_fixed` (only set after an actual successful API check) is what stops
    # this from re-checking the same book forever. A title that "looks clean" can still be a
    # publisher subtitle fragment or missing spaces, which no pattern list reliably catches.
    rows = await fetch_all(
        """
        SELECT id, isbn, title FROM books
        WHERE isbn IS NOT NULL AND length(isbn) >= 10 AND identity_status = 'auto'
          AND extra_metadata IS DISTINCT FROM extra_metadata || '{"title_fixed": true}'::jsonb
        LIMIT $1
    """,
        limit,
    )

    fixed = 0
    client = get_client()
    for r in rows:
        await rate_limiter.wait("google")
        try:
            gb_params = {"q": f"isbn:{r['isbn']}", "maxResults": 1}
            if settings.google_books_api_key:
                gb_params["key"] = settings.google_books_api_key
            resp = await client.get("https://www.googleapis.com/books/v1/volumes", params=gb_params)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    vi = items[0]["volumeInfo"]
                    api_title = vi.get("title", "")
                    sub = vi.get("subtitle", "")
                    full = f"{api_title}: {sub}" if sub else api_title

                    if len(full) > 3 and full != r["title"]:
                        await execute("UPDATE books SET title = $1 WHERE id = $2", full, r["id"])
                        # Record the title change as filename history
                        from brainycat.filename_history import record_rename
                        await record_rename(r["id"], "title_cleanup_api", r["title"], full)
                        fixed += 1

                    # Also grab any extra metadata while we're here
                    desc = vi.get("description")
                    if desc:
                        await execute(
                            "UPDATE books SET description = $1 WHERE id = $2 AND (description IS NULL OR description = '')",
                            desc[:2000],
                            r["id"],
                        )
                    cats = vi.get("categories", [])
                    if cats:
                        for cat in cats[:5]:
                            await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", cat)
                            tag = await fetch_one("SELECT id FROM tags WHERE name = $1", cat)
                            if tag:
                                await execute(
                                    "INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                                    r["id"],
                                    tag["id"],
                                )

                # Mark as checked so we don't retry — only on a real response. A failed call (rate
                # limit, timeout, etc.) must NOT set this, or the book is silently skipped forever
                # even though it was never actually checked.
                await execute(
                    "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || '{\"title_fixed\": true}'::jsonb WHERE id = $1",
                    r["id"],
                )
            elif resp.status_code == 429:
                await rate_limiter.record_failure("google")
                break  # stop hammering an exhausted quota; leave remaining candidates unflagged
        except Exception:
            pass
    return {"fixed": fixed, "checked": len(rows)}


async def regen_covers_after_cleanup(limit: int = 5) -> dict[str, int]:
    """Regenerate covers for books whose titles were recently cleaned."""
    import os

    from brainycat.atomic import atomic_write
    from brainycat.covers import generate_cover
    from brainycat.storage import book_dir

    rows = await fetch_all(
        """
        SELECT b.id, b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.quality_score = 0 AND b.cover_path IS NOT NULL
        GROUP BY b.id LIMIT $1
    """,
        limit,
    )
    regen = 0
    for r in rows:
        try:
            data = generate_cover(r["title"], ", ".join(r["authors"] or []))
            if data:
                path = os.path.join(book_dir(str(r["id"])), "cover.jpg")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with atomic_write(path) as f:
                    f.write(data)
                await execute("UPDATE books SET cover_path = $1 WHERE id = $2", path, r["id"])
                regen += 1
        except Exception:
            pass
    return {"regenerated": regen}


async def cleanup_titles_regex(limit: int = 20) -> dict[str, int]:
    """Regex cleanup of obviously dirty titles."""
    await execute("""
        UPDATE books SET title = trim(regexp_replace(
          regexp_replace(
            regexp_replace(
              regexp_replace(title,
                E'\\s*--\\s*[0-9a-f]{20,}.*$', '', 'i'),
              E'\\s*--\\s*Anna.s Archive.*$', '', 'i'),
            E'\\s*-\\s*libgen\\.li.*$', '', 'i'),
          E'^\\[.*?\\]\\s*', ''))
        WHERE (title ILIKE '%libgen%' OR title ILIKE '%anna%archive%' OR title ~ '[0-9a-f]{20,}')
          AND identity_status = 'auto'
          AND length(trim(regexp_replace(
            regexp_replace(
              regexp_replace(
                regexp_replace(title,
                  E'\\s*--\\s*[0-9a-f]{20,}.*$', '', 'i'),
                E'\\s*--\\s*Anna.s Archive.*$', '', 'i'),
              E'\\s*-\\s*libgen\\.li.*$', '', 'i'),
            E'^\\[.*?\\]\\s*', ''))) > 5
    """)
    return {"cleaned": 0}  # execute doesn't return count easily


async def run_title_cleanup_cycle() -> dict[str, Any]:
    """One cycle of the title cleanup background process."""
    r5 = await apply_local_title_parse(30)
    r0 = await extract_isbn_from_title(10)
    r1 = await extract_isbn_from_filename(10)
    r2 = await fix_titles_from_api(5)
    r3 = await ocr_last_pages_for_isbn(3)
    r4 = await decode_html_entities(50)
    return {
        "local_title_parse": r5,
        "isbn_from_title": r0,
        "isbn_from_filename": r1,
        "api_title_fix": r2,
        "isbn_from_ocr": r3,
        "html_entities": r4,
    }


async def ocr_last_pages_for_isbn(limit: int = 3) -> dict[str, int]:
    """OCR last pages of scanned PDFs that have no ISBN."""
    rows = await fetch_all(
        """
        SELECT b.id FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        WHERE b.isbn IS NULL AND bf.format = 'pdf' AND bf.file_size > 500000
          AND (b.extra_metadata IS NULL OR NOT extra_metadata ? 'isbn_ocr_tried')
        LIMIT $1
    """,
        limit,
    )
    found = 0
    for r in rows:
        from brainycat.isbn import ocr_last_page_for_isbn

        result = await ocr_last_page_for_isbn(str(r["id"]))
        if result.get("ok"):
            found += 1
        # Mark as tried so we don't retry
        import json as _j

        await execute(
            "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $2::jsonb WHERE id = $1",
            r["id"],
            _j.dumps({"isbn_ocr_tried": True}),
        )
    return {"found": found, "checked": len(rows)}
