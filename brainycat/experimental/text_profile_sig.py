"""TextProfileSignature: Apache Nutch-style fuzzy hash for near-duplicate detection.

Tokenizes text, counts frequencies, quantizes, and hashes.
More robust than SimHash for reformatted text (different line breaks, added prefaces).

Config: BRAINYCAT_EXP_TEXT_PROFILE=1
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter


def text_profile_signature(text: str, min_token_len: int = 2, quant_rate: float = 0.01) -> str:
    """Generate a TextProfileSignature hash (MD5 of quantized token profile)."""
    tokens = re.findall(r"\b\w+\b", text.lower())
    tokens = [t for t in tokens if len(t) >= min_token_len]
    if not tokens:
        return ""

    freq = Counter(tokens)
    max_freq = max(freq.values())
    quant_step = max(1, int(max_freq * quant_rate))

    profile = []
    for token, count in sorted(freq.items()):
        quantized = count // quant_step
        if quantized > 0:
            profile.append(f"{token}{quantized}")

    return hashlib.md5("".join(profile).encode()).hexdigest()


async def compare_with_library(text: str, book_id: str) -> dict | None:
    """Compare a book's text profile against all existing profiles in DB."""
    from brainycat.db import fetch_one

    sig = text_profile_signature(text[:50000])
    if not sig:
        return None

    match = await fetch_one(
        "SELECT book_id FROM book_signatures WHERE text_profile = $1 AND book_id != $2",
        sig,
        book_id,
    )
    if match:
        return {"duplicate_of": match["book_id"], "method": "text_profile", "exact": True}
    return None
