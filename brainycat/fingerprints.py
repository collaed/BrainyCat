"""Book fingerprinting — extract 16x2KB text samples, store, compare for duplicates."""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one

SAMPLE_SIZE = 2000
NUM_SAMPLES = 16


def _normalize_sample(text: str) -> str:
    """Strip punctuation, lowercase, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_samples(file_path: str, fmt: str) -> list[str]:
    """Extract 16 evenly-spaced 2KB text samples from a book."""
    full_text = ""
    try:
        if fmt == "epub":
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            book = epub.read_epub(file_path, options={"ignore_ncx": True})
            parts = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                # Skip TOC, copyright, "by the same author" sections
                text = soup.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    parts.append(text)
            full_text = " ".join(parts)

        elif fmt == "pdf":
            import fitz

            doc = fitz.open(file_path)
            parts = []
            for page in doc:
                text = page.get_text()
                if len(text) > 100:
                    parts.append(text)
            doc.close()
            full_text = " ".join(parts)
    except Exception:
        return []

    if len(full_text) < SAMPLE_SIZE * 2:
        return []

    full_text = _normalize_sample(full_text)
    total = len(full_text)

    # Skip first 10% and last 10% (preface, postface, "also by author")
    start = int(total * 0.1)
    end = int(total * 0.9)
    usable = full_text[start:end]

    if len(usable) < SAMPLE_SIZE * NUM_SAMPLES // 2:
        return []

    # Extract evenly spaced samples
    samples = []
    step = len(usable) // NUM_SAMPLES
    for i in range(NUM_SAMPLES):
        offset = i * step
        sample = usable[offset : offset + SAMPLE_SIZE]
        if len(sample) >= SAMPLE_SIZE // 2:
            samples.append(sample)

    return samples


def _compare_samples(samples_a: list[str], samples_b: list[str]) -> tuple[int, int, float]:
    """Compare two sets of samples. Returns (matching, total, overlap_pct)."""
    if not samples_a or not samples_b:
        return 0, 0, 0.0

    matching = 0
    total = min(len(samples_a), len(samples_b))

    for sa in samples_a:
        for sb in samples_b:
            # Check if 80% of a 200-char substring from sa exists in sb
            # This allows ~2% variation
            chunk = sa[len(sa) // 4 : len(sa) // 4 + 200]
            if len(chunk) < 100:
                continue
            if chunk in sb:
                matching += 1
                break
            # Try smaller chunks for fuzzy match (allows typos/hyphens)
            sub = chunk[20:160]
            if sub in sb:
                matching += 1
                break

    pct = (matching / total * 100) if total > 0 else 0.0
    return matching, total, pct


async def compute_fingerprint(book_id: str) -> dict[str, Any]:
    """Compute and store fingerprint for a single book."""
    row = await fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf WHERE bf.book_id = $1 AND bf.format IN ('epub','pdf') LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"ok": False, "reason": "no file"}

    samples = _extract_samples(row["file_path"], row["format"])
    if not samples:
        return {"ok": False, "reason": "too short"}

    await execute(
        """INSERT INTO book_fingerprints (book_id, samples, sample_count, total_chars, computed_at)
           VALUES ($1, $2, $3, $4, now())
           ON CONFLICT (book_id) DO UPDATE SET samples = $2, sample_count = $3, total_chars = $4, computed_at = now()""",
        UUID(book_id),
        samples,
        len(samples),
        sum(len(s) for s in samples),
    )
    return {"ok": True, "samples": len(samples)}


async def compute_all_fingerprints(batch_size: int = 20) -> dict[str, Any]:
    """Compute fingerprints for books that don't have them yet."""
    rows = await fetch_all(
        """
        SELECT b.id FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
        LIMIT $1
    """,
        batch_size,
    )

    computed = 0
    for r in rows:
        result = await compute_fingerprint(str(r["id"]))
        if result.get("ok"):
            computed += 1

    total = await fetch_one("SELECT count(*) as n FROM book_fingerprints")
    pending = await fetch_one("""
        SELECT count(*) as n FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
    """)

    return {"computed": computed, "total_fingerprinted": total["n"] if total else 0, "pending": pending["n"] if pending else 0}


async def find_duplicates_by_content(batch_size: int = 50) -> dict[str, Any]:
    """Compare fingerprints to find content duplicates."""
    rows = await fetch_all("""
        SELECT fp.book_id, fp.samples, b.title
        FROM book_fingerprints fp JOIN books b ON b.id = fp.book_id
        WHERE fp.sample_count >= 4
        ORDER BY b.title
    """)

    books = [dict(r) for r in rows]
    new_matches = 0

    for i, a in enumerate(books):
        if i >= batch_size:
            break
        for b in books[i + 1 :]:
            # Skip already checked pairs
            existing = await fetch_one(
                "SELECT id FROM duplicate_matches WHERE (book_a_id = $1 AND book_b_id = $2) OR (book_a_id = $2 AND book_b_id = $1)",
                a["book_id"],
                b["book_id"],
            )
            if existing:
                continue

            matching, total, pct = _compare_samples(a["samples"], b["samples"])
            if pct >= 30:  # At least 30% sample overlap
                await execute(
                    """INSERT INTO duplicate_matches (book_a_id, book_b_id, overlap_pct, matching_samples, total_samples)
                       VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING""",
                    a["book_id"],
                    b["book_id"],
                    pct,
                    matching,
                    total,
                )
                new_matches += 1

    total_matches = await fetch_one("SELECT count(*) as n FROM duplicate_matches WHERE status = 'pending'")
    return {"new_matches": new_matches, "total_pending": total_matches["n"] if total_matches else 0}


async def get_duplicate_matches() -> list[dict[str, Any]]:
    """Get pending duplicate matches for review."""
    rows = await fetch_all("""
        SELECT dm.*, ba.title as title_a, bb.title as title_b,
               array_agg(DISTINCT aa.name) FILTER (WHERE aa.name IS NOT NULL) as authors_a,
               array_agg(DISTINCT ab.name) FILTER (WHERE ab.name IS NOT NULL) as authors_b
        FROM duplicate_matches dm
        JOIN books ba ON ba.id = dm.book_a_id
        JOIN books bb ON bb.id = dm.book_b_id
        LEFT JOIN books_authors baa ON baa.book_id = dm.book_a_id LEFT JOIN authors aa ON aa.id = baa.author_id
        LEFT JOIN books_authors bab ON bab.book_id = dm.book_b_id LEFT JOIN authors ab ON ab.id = bab.author_id
        WHERE dm.status = 'pending'
        GROUP BY dm.id, ba.title, bb.title
        ORDER BY dm.overlap_pct DESC
    """)
    return [
        {
            "id": str(r["id"]),
            "book_a": str(r["book_a_id"]),
            "title_a": r["title_a"],
            "authors_a": r["authors_a"] or [],
            "book_b": str(r["book_b_id"]),
            "title_b": r["title_b"],
            "authors_b": r["authors_b"] or [],
            "overlap_pct": round(r["overlap_pct"], 1),
            "matching_samples": r["matching_samples"],
            "total_samples": r["total_samples"],
        }
        for r in rows
    ]


async def resolve_match(match_id: str, action: str) -> dict[str, bool]:
    """Resolve a duplicate match: confirmed, dismissed, or linked."""
    await execute("UPDATE duplicate_matches SET status = $1 WHERE id = $2", action, UUID(match_id))
    return {"ok": True}
