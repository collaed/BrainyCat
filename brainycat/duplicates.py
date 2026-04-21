"""Content-based duplicate detection — text fingerprinting from book midpoints."""

from __future__ import annotations

import os
from typing import Any

from brainycat.db import fetch_all


def _extract_text_sample(file_path: str, fmt: str, sample_size: int = 2000) -> str | None:
    """Extract ~2000 chars from the middle of a book."""
    try:
        if fmt == "epub":
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            book = epub.read_epub(file_path, options={"ignore_ncx": True})
            texts = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                texts.append(soup.get_text(separator=" ", strip=True))
            full = " ".join(texts)
            if len(full) < 500:
                return None
            mid = len(full) // 2
            return _normalize_text(full[mid - sample_size // 2 : mid + sample_size // 2])

        if fmt == "pdf":
            import fitz

            doc = fitz.open(file_path)
            if len(doc) < 3:
                return None
            mid_page = len(doc) // 2
            text = ""
            for p in range(max(0, mid_page - 2), min(len(doc), mid_page + 3)):
                text += doc[p].get_text()
            doc.close()
            if len(text) < 500:
                return None
            mid = len(text) // 2
            return _normalize_text(text[mid - sample_size // 2 : mid + sample_size // 2])
    except Exception:
        pass
    return None


def _normalize_text(text: str) -> str:
    """Normalize for comparison: lowercase, collapse whitespace, strip punctuation."""
    import re

    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _text_similarity(a: str, b: str) -> float:
    """Compare two text samples. Returns 0-1 similarity using longest common substring ratio."""
    if not a or not b:
        return 0.0
    # Use character-level comparison — find longest common substring
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 100:
        return 0.0

    # Sliding window: check if a 200-char chunk from A exists in B (with tolerance)
    chunk_size = 200
    matches = 0
    checks = 0
    step = chunk_size // 2
    for i in range(0, len(shorter) - chunk_size, step):
        chunk = shorter[i : i + chunk_size]
        checks += 1
        # Check if chunk appears in longer text (allow 2% difference via substring search)
        if chunk in longer:
            matches += 1
        else:
            # Try smaller sub-chunks for fuzzy match
            sub = chunk[50:150]  # 100-char core
            if sub in longer:
                matches += 0.7

    return matches / checks if checks > 0 else 0.0


async def find_content_duplicates(limit: int = 50) -> list[dict[str, Any]]:
    """Find duplicates by comparing text content from book midpoints."""
    rows = await fetch_all("""
        SELECT b.id, b.title, bf.file_path, bf.format, bf.file_size,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN books_authors ba ON ba.book_id = b.id
        LEFT JOIN authors a ON a.id = ba.author_id
        WHERE bf.format IN ('epub', 'pdf')
        GROUP BY b.id, bf.file_path, bf.format, bf.file_size
        ORDER BY b.title
    """)

    # Extract text samples (cached in memory for this run)
    samples: dict[str, str] = {}
    for r in rows:
        if os.path.isfile(r["file_path"]):
            sample = _extract_text_sample(r["file_path"], r["format"])
            if sample:
                samples[str(r["id"])] = sample

    # Compare pairs
    dupes = []
    ids = list(samples.keys())
    book_map = {str(r["id"]): r for r in rows}

    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            sim = _text_similarity(samples[id_a], samples[id_b])
            if sim > 0.5:
                a, b = book_map[id_a], book_map[id_b]
                dupes.append(
                    {
                        "book_a": id_a,
                        "title_a": a["title"],
                        "book_b": id_b,
                        "title_b": b["title"],
                        "similarity": round(sim * 100),
                        "method": "content_fingerprint",
                        "authors_a": a["authors"] or [],
                        "authors_b": b["authors"] or [],
                    }
                )
                if len(dupes) >= limit:
                    return dupes

    dupes.sort(key=lambda d: d["similarity"], reverse=True)
    return dupes
