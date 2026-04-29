"""MinHash LSH dedup using datasketch library.

Scales to thousands of books. Uses shingles (5-word windows) and
MinHash signatures for O(1) approximate nearest-neighbor lookup.

Config: BRAINYCAT_EXP_LSH_DEDUP=1
"""

from __future__ import annotations

import re

from datasketch import MinHash, MinHashLSH

_lsh: MinHashLSH | None = None


def text_to_minhash(text: str, num_perm: int = 128, shingle_size: int = 5) -> MinHash:
    """Convert text to MinHash signature using word shingles."""
    words = re.findall(r"\b\w+\b", text.lower())[:5000]
    m = MinHash(num_perm=num_perm)
    for i in range(len(words) - shingle_size + 1):
        shingle = " ".join(words[i : i + shingle_size])
        m.update(shingle.encode("utf-8"))
    return m


def get_lsh(threshold: float = 0.5, num_perm: int = 128) -> MinHashLSH:
    """Get or create the LSH index."""
    global _lsh
    if _lsh is None:
        _lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    return _lsh


def insert_book(book_id: str, text: str) -> None:
    """Insert a book's MinHash into the LSH index."""
    lsh = get_lsh()
    m = text_to_minhash(text)
    try:
        lsh.insert(book_id, m)
    except ValueError:
        pass  # Already exists


def query_similar(text: str) -> list[str]:
    """Find similar books in the LSH index."""
    lsh = get_lsh()
    m = text_to_minhash(text)
    return lsh.query(m)
