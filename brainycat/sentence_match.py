"""Sentence-based book identification — fallback when ISBN/title matching fails.

Strategy:
1. Extract the first substantial sentence (opening lines are crafted to be memorable)
2. Google search it in quotes → if exactly 1 book result, match
3. If too many hits, pick an unusual sentence from ~60% into the book and retry
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from brainycat.config import settings
from brainycat.content_guard import _sample_epub, _sample_pdf
from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client
from brainycat.rate_limit import rate_limiter


def _extract_sentences(text: str) -> list[str]:
    """Split text into sentences, return those with 8+ words."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if len(s.split()) >= 8 and len(s) < 300]


def _pick_unusual(sentences: list[str]) -> str | None:
    """Pick the most unusual sentence (fewest common words)."""
    common = {"the", "and", "was", "that", "with", "for", "his", "her", "had", "not",
              "but", "have", "from", "they", "been", "this", "which", "were", "are",
              "les", "des", "une", "que", "dans", "pour", "qui", "avec", "est", "pas"}
    best, best_score = None, 1.0
    for s in sentences:
        words = s.lower().split()
        if len(words) < 8:
            continue
        ratio = sum(1 for w in words if w in common) / len(words)
        if ratio < best_score:
            best_score = ratio
            best = s
    return best


async def _google_sentence(sentence: str) -> dict[str, Any] | None:
    """Search Google Books for a quoted sentence. Returns book info or None."""
    await rate_limiter.wait("google")
    client = get_client()
    query = f'"{sentence}"'
    try:
        resp = await client.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": query, "maxResults": 3},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items", [])
        if len(items) == 1:
            vi = items[0]["volumeInfo"]
            return {
                "title": vi.get("title"),
                "authors": vi.get("authors", []),
                "isbn": next((i["identifier"] for i in vi.get("industryIdentifiers", []) if i["type"] == "ISBN_13"), None),
                "description": vi.get("description"),
                "publisher": vi.get("publisher"),
                "language": vi.get("language"),
                "source": "google_sentence",
                "match_type": "opening_line",
            }
        # Too many or zero results
        return {"hits": len(items)}
    except Exception:
        return None


async def identify_by_sentence(book_id: str) -> dict[str, Any]:
    """Try to identify a book by searching its opening sentence on Google."""
    file_row = await fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 ORDER BY created_at LIMIT 1",
        UUID(book_id),
    )
    if not file_row:
        return {"ok": False, "reason": "no file"}

    import os
    if not os.path.isfile(file_row["file_path"]):
        return {"ok": False, "reason": "file missing"}

    # Get text samples
    fmt = file_row["format"]
    path = file_row["file_path"]
    if fmt == "epub":
        samples = _sample_epub(path)
    elif fmt == "pdf":
        samples = _sample_pdf(path)
    else:
        return {"ok": False, "reason": "unsupported format"}

    if not samples:
        return {"ok": False, "reason": "no text extracted"}

    # Strategy 1: first substantial sentence from the opening
    opening_text = samples[0] if samples else ""
    sentences = _extract_sentences(opening_text)
    if not sentences:
        return {"ok": False, "reason": "no usable sentences"}

    first_sentence = sentences[0]
    result = await _google_sentence(first_sentence)

    if result and "title" in result:
        result["matched_sentence"] = first_sentence
        await _apply_match(book_id, result)
        return {"ok": True, **result}

    # Strategy 2: too many hits on opening → pick unusual sentence from later
    later_text = samples[1] if len(samples) > 1 else (samples[0][len(samples[0])//2:] if samples else "")
    later_sentences = _extract_sentences(later_text)
    unusual = _pick_unusual(later_sentences)

    if unusual:
        result2 = await _google_sentence(unusual)
        if result2 and "title" in result2:
            result2["matched_sentence"] = unusual
            result2["match_type"] = "unusual_sentence"
            await _apply_match(book_id, result2)
            return {"ok": True, **result2}

    return {"ok": False, "reason": "no unique match", "tried": [first_sentence[:80]]}


async def _apply_match(book_id: str, match: dict[str, Any]) -> None:
    """Apply a sentence-match result to the book record."""
    from brainycat.metadata_audit import record_change

    book = await fetch_one("SELECT title, isbn FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return

    if match.get("title") and match["title"] != book["title"]:
        await record_change(book_id, "title", book["title"], match["title"], "sentence_match")
        await execute("UPDATE books SET title = $1 WHERE id = $2", match["title"], UUID(book_id))

    if match.get("isbn") and not book["isbn"]:
        await record_change(book_id, "isbn", None, match["isbn"], "sentence_match")
        await execute("UPDATE books SET isbn = $1 WHERE id = $2", match["isbn"], UUID(book_id))

    if match.get("authors"):
        for name in match["authors"]:
            await execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT DO NOTHING", name)
            row = await fetch_one("SELECT id FROM authors WHERE name = $1", name)
            if row:
                await execute("INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                              UUID(book_id), row["id"])
