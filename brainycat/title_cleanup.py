"""Title cleanup — background process to fix dirty titles.

Runs as part of the scheduler. Three strategies:
1. ISBN-from-filename: extract ISBNs embedded in filenames
2. API title lookup: fetch canonical title from Google Books by ISBN
3. Filename cleanup: strip libgen.li, Anna's Archive, author prefixes
"""

from __future__ import annotations

import re
from typing import Any

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client
from brainycat.isbn import _clean_isbn
from brainycat.rate_limit import rate_limiter


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
    rows = await fetch_all(
        """
        SELECT id, isbn, title FROM books
        WHERE isbn IS NOT NULL AND length(isbn) >= 10
          AND (title LIKE '%,%' AND title LIKE '% - %'
               OR title LIKE '%(20%' OR title LIKE '%(19%'
               OR title LIKE '%libgen%' OR title LIKE '%[%]%')
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
            resp = await client.get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{r['isbn']}&maxResults=1")
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    vi = items[0]["volumeInfo"]
                    api_title = vi.get("title", "")
                    sub = vi.get("subtitle", "")
                    full = f"{api_title}: {sub}" if sub else api_title

                    if len(full) > 3 and full != r["title"]:
                        await execute("UPDATE books SET title = $1 WHERE id = $2", full, r["id"])
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

            # Mark as checked so we don't retry
            await execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || '{\"title_fixed\": true}'::jsonb WHERE id = $1",
                r["id"],
            )
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
    r1 = await extract_isbn_from_filename(10)
    r2 = await fix_titles_from_api(5)
    return {"isbn_from_filename": r1, "api_title_fix": r2}
