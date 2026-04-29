"""Relevance guard — prevents enrichment from applying wrong metadata.

The ESXi Cookbook incident: Intello returned the same cached result for every query,
causing 108 books to be renamed. This guard ensures API results actually match
the book being enriched before applying them.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def title_similarity(a: str, b: str) -> float:
    """Calculate similarity between two titles (0.0-1.0)."""
    a_clean = _normalize(a)
    b_clean = _normalize(b)
    if not a_clean or not b_clean:
        return 0.0
    return SequenceMatcher(None, a_clean, b_clean).ratio()


def _normalize(title: str) -> str:
    """Normalize title for comparison."""
    t = title.lower().strip()
    # Remove common prefixes/suffixes
    t = re.sub(r"^(head first|o'reilly|packt)\s*[-:]\s*", "", t)
    # Remove edition markers
    t = re.sub(r"\b\d+(st|nd|rd|th)\s+ed(ition)?\b", "", t)
    t = re.sub(r"\b(second|third|fourth|fifth)\s+edition\b", "", t)
    # Remove punctuation
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_relevant(query_title: str, result_title: str, result_isbn: str | None = None, book_isbn: str | None = None) -> bool:
    """Check if an enrichment result is relevant to the book being enriched.

    Returns True if the result should be applied, False if it should be rejected.
    """
    # ISBN match is always relevant (strongest signal)
    if book_isbn and result_isbn and book_isbn == result_isbn:
        return True

    # If ISBNs both exist but don't match — reject
    if book_isbn and result_isbn and book_isbn != result_isbn:
        # Unless titles are very similar (different editions)
        sim = title_similarity(query_title, result_title)
        return sim > 0.6

    # Title similarity check
    sim = title_similarity(query_title, result_title)

    # High similarity — accept
    if sim > 0.5:
        return True

    # Check if one contains the other (subtitle matching)
    q_norm = _normalize(query_title)
    r_norm = _normalize(result_title)
    if q_norm in r_norm or r_norm in q_norm:
        return True

    # Low similarity — reject
    return False
