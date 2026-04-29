"""Vocabulary difficulty scoring — analyze word frequency for language learners."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Top 3000 English words (simplified — in production, use wordfreq library)
_COMMON_WORDS: set[str] | None = None


def _get_common_words() -> set[str]:
    global _COMMON_WORDS
    if _COMMON_WORDS is None:
        try:
            from wordfreq import top_n_list

            _COMMON_WORDS = set(top_n_list("en", 5000))
        except ImportError:
            # Fallback: basic set
            _COMMON_WORDS = set()
    return _COMMON_WORDS


async def analyze_vocabulary(book_id: str) -> dict[str, Any]:
    """Analyze vocabulary difficulty of a book."""
    from uuid import UUID

    import fitz

    from brainycat.db import fetch_one

    row = await fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf WHERE bf.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no file"}

    # Extract text
    text = ""
    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        for i in range(min(50, len(doc))):
            text += doc[i].get_text() + " "
        doc.close()
    elif row["format"] == "epub":
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text() + " "
            if len(text.split()) > 20000:
                break

    # Analyze
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    if not words:
        return {"error": "no text extracted"}

    total = len(words)
    unique = set(words)
    freq = Counter(words)
    common = _get_common_words()

    # Categorize
    if common:
        known = unique & common
        advanced = unique - common
        coverage = len(known) / len(unique) * 100 if unique else 0
    else:
        known = set()
        advanced = unique
        coverage = 0

    # Difficulty level (rough CEFR mapping)
    unique_ratio = len(unique) / total if total else 0
    if unique_ratio < 0.05:
        level = "A1-A2 (Beginner)"
    elif unique_ratio < 0.08:
        level = "B1 (Intermediate)"
    elif unique_ratio < 0.12:
        level = "B2 (Upper Intermediate)"
    else:
        level = "C1-C2 (Advanced)"

    return {
        "total_words": total,
        "unique_words": len(unique),
        "vocabulary_richness": round(unique_ratio * 100, 1),
        "estimated_level": level,
        "common_word_coverage": round(coverage, 1),
        "advanced_words_sample": sorted(advanced, key=lambda w: freq[w], reverse=True)[:20],
        "most_frequent": [{"word": w, "count": c} for w, c in freq.most_common(10)],
    }
