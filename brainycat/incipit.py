"""Incipit & characteristic sentence extraction for book identification.

Extracts:
1. Incipit: first meaningful sentence of the book (skipping front matter)
2. Longest sentence: most distinctive by length
3. Rarest words: words least likely to appear in other books
4. Longest words: unusual compound/technical terms
"""

from __future__ import annotations

import re
from typing import Any

from brainycat.stopwords import STOPWORDS

# Patterns to skip front matter
_FRONT_MATTER_RE = re.compile(
    r"(?:table\s+(?:of\s+)?contents|copyright|all\s+rights\s+reserved|"
    r"published\s+by|isbn|acknowledgements?|dedication|preface|foreword|"
    r"table\s+des\s+matières|tous\s+droits\s+réservés|sommaire|préface|"
    r"avant-propos|remerciements|inhaltsverzeichnis|vorwort|widmung)",
    re.IGNORECASE,
)

_SENTENCE_RE = re.compile(r"[A-ZÀ-Ü][^.!?]*[.!?]", re.DOTALL)


def extract_characteristics(text: str) -> dict[str, Any]:
    """Extract incipit and characteristic sentences from book text."""
    if not text or len(text) < 200:
        return {}

    result: dict[str, Any] = {}

    # Find where actual content starts (skip front matter)
    content_start = 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i > 200:  # don't scan more than 200 lines for front matter
            break
        if _FRONT_MATTER_RE.search(line):
            content_start = text.index(line) + len(line)

    body = text[content_start:content_start + 50000]  # first 50K of body

    # 1. Incipit: first real sentence (>20 chars, not metadata)
    sentences = _SENTENCE_RE.findall(body)
    for s in sentences:
        s = s.strip()
        if len(s) > 20 and not _FRONT_MATTER_RE.search(s):
            result["incipit"] = s[:500]
            break

    # Use full text (capped at 500K) for word/sentence analysis
    analysis_text = text[:500000]
    all_sentences = _SENTENCE_RE.findall(analysis_text)
    all_sentences = [s.strip() for s in all_sentences if 20 < len(s.strip()) < 2000]

    # 2. Longest sentence
    if all_sentences:
        longest = max(all_sentences, key=len)
        result["longest_sentence"] = longest[:1000]

    # 3. Longest words (likely technical/specific terms)
    words = re.findall(r"[a-zA-ZÀ-ÿ\u00C0-\u024F]{2,}", analysis_text)
    words_lower = [w.lower() for w in words]
    unique_words = set(words_lower) - STOPWORDS
    longest_words = sorted(unique_words, key=len, reverse=True)[:10]
    if longest_words:
        result["longest_words"] = longest_words

    # 4. Most specific words (rare in general, appear in this book)
    # Use word frequency as proxy: words that appear 2-5 times are more specific
    # than words appearing once (typos) or many times (common)
    from collections import Counter
    freq = Counter(w for w in words_lower if w in unique_words and len(w) > 4)
    specific = [w for w, c in freq.items() if 2 <= c <= 5 and len(w) >= 7]
    specific.sort(key=len, reverse=True)
    if specific:
        result["specific_words"] = specific[:15]

    return result
