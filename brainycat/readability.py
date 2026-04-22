"""Reading difficulty scoring — Lexile-like readability assessment.

Computes: Flesch-Kincaid grade, Flesch reading ease, syllable density,
average sentence length. Stores as book metadata.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one


def compute_readability(text: str) -> dict[str, Any]:
    """Compute readability metrics for a text."""
    if not text or len(text) < 100:
        return {"error": "text too short"}

    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    words = re.findall(r"[a-zA-ZÀ-ÿ]+", text)

    if not sentences or not words:
        return {"error": "no content"}

    num_sentences = len(sentences)
    num_words = len(words)
    num_syllables = sum(_count_syllables(w) for w in words)

    avg_sentence_len = num_words / num_sentences
    avg_syllables = num_syllables / num_words

    # Flesch Reading Ease: 206.835 - 1.015*(words/sentences) - 84.6*(syllables/words)
    flesch_ease = 206.835 - 1.015 * avg_sentence_len - 84.6 * avg_syllables

    # Flesch-Kincaid Grade: 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
    fk_grade = 0.39 * avg_sentence_len + 11.8 * avg_syllables - 15.59

    # Difficulty label
    if flesch_ease >= 80:
        level = "easy"
    elif flesch_ease >= 60:
        level = "standard"
    elif flesch_ease >= 40:
        level = "moderate"
    elif flesch_ease >= 20:
        level = "difficult"
    else:
        level = "very_difficult"

    return {
        "flesch_ease": round(flesch_ease, 1),
        "fk_grade": round(max(0, fk_grade), 1),
        "avg_sentence_length": round(avg_sentence_len, 1),
        "avg_syllables_per_word": round(avg_syllables, 2),
        "level": level,
        "word_count": num_words,
        "sentence_count": num_sentences,
    }


def _count_syllables(word: str) -> int:
    """Estimate syllable count for an English word."""
    word = word.lower().strip()
    if len(word) <= 3:
        return 1
    # Remove trailing e
    if word.endswith("e"):
        word = word[:-1]
    # Count vowel groups
    count = len(re.findall(r"[aeiouy]+", word))
    return max(1, count)


async def score_book_readability(book_id: str) -> dict[str, Any]:
    """Compute and store readability for a book."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub"}

    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text(separator=" ", strip=True) + " "
            if len(text) > 50000:
                break  # Sample first ~50K chars
    except Exception as e:
        return {"error": str(e)[:100]}

    result = compute_readability(text)
    if "error" not in result:
        import json

        await execute(
            "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
            json.dumps({"readability": result}),
            UUID(book_id),
        )
    return result
