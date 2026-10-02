"""Metadata validation — cross-check enrichment data against actual book content.

Runs after a book has both enrichment metadata AND text profile data.
Flags mismatches in extra_metadata.validation_flags.

Checks:
1. Title presence in text (wrong file detection)
2. Language match (detected vs assigned)
3. Author presence in front matter
4. Description similarity to content (wrong book match)
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


def _normalize(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def _title_in_text(title: str, text_start: str) -> bool:
    """Check if title (or significant portion) appears in first 5000 chars."""
    norm_title = _normalize(title)
    norm_text = _normalize(text_start)
    # Full title match
    if norm_title in norm_text:
        return True
    # Try significant words (3+ chars, skip stopwords)
    words = [w for w in norm_title.split() if len(w) > 3]
    if not words:
        return True  # can't validate very short titles
    matches = sum(1 for w in words if w in norm_text)
    return matches >= len(words) * 0.6


def _detect_language(text: str) -> str | None:
    """Detect language from text sample."""
    try:
        from langdetect import detect
        return detect(text[:3000])
    except Exception:
        return None


def _author_in_text(author_names: list[str], text_start: str) -> bool:
    """Check if any author name appears in front matter."""
    if not author_names:
        return True  # can't validate
    norm_text = _normalize(text_start)
    for name in author_names:
        # Check last name (most reliable)
        parts = name.strip().split()
        if parts:
            last = _normalize(parts[-1])
            if len(last) > 2 and last in norm_text:
                return True
    return False


async def validate_book(book_id: str) -> dict[str, Any]:
    """Run all validation checks on a book. Returns flags dict."""
    row = await fetch_one("""
        SELECT b.id, b.title, b.description, b.extra_metadata,
               array_agg(DISTINCT l.code) FILTER (WHERE l.code IS NOT NULL) as languages,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_languages bl ON bl.book_id = b.id
        LEFT JOIN languages l ON l.id = bl.language_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id
        LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1
        GROUP BY b.id
    """, UUID(book_id))

    if not row:
        return {"error": "not found"}

    extra = row["extra_metadata"] if isinstance(row["extra_metadata"], dict) else {}
    if isinstance(row["extra_metadata"], str):
        import json as _json
        try:
            extra = _json.loads(row["extra_metadata"])
        except (ValueError, TypeError):
            extra = {}
    incipit = extra.get("incipit", "")
    if not incipit:
        return {"skipped": "no text profile yet"}

    # Use incipit + longest_sentence as text sample
    text_sample = incipit + " " + extra.get("longest_sentence", "")

    flags: dict[str, Any] = {}

    # 1. Title in text
    if row["title"] and len(row["title"]) > 5:
        if not _title_in_text(row["title"], text_sample):
            flags["title_mismatch"] = True

    # 2. Language check
    assigned_langs = row["languages"] or []
    if assigned_langs and len(text_sample) > 200:
        detected = _detect_language(text_sample)
        if detected:
            # Map between ISO 639-1 (langdetect) and ISO 639-2 (DB)
            iso1_to_2 = {"en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita",
                         "pt": "por", "nl": "nld", "ru": "rus", "ja": "jpn", "zh": "zho",
                         "ar": "ara", "ko": "kor", "sv": "swe", "da": "dan", "no": "nor",
                         "fi": "fin", "pl": "pol", "cs": "ces", "ro": "ron", "hu": "hun",
                         "el": "ell", "tr": "tur", "he": "heb", "ca": "cat", "uk": "ukr"}
            detected_3 = iso1_to_2.get(detected, detected)
            aliases = {"zh-cn": "zho", "zh-tw": "zho", "pt-br": "por"}
            detected_3 = aliases.get(detected, detected_3)
            if detected_3 not in assigned_langs and detected not in assigned_langs:
                flags["language_mismatch"] = {"detected": detected, "assigned": assigned_langs}

    # 3. Author in text
    if row["authors"] and not _author_in_text(row["authors"], text_sample):
        flags["author_not_in_text"] = True

    # 4. Description vs content similarity (simple word overlap)
    if row["description"] and len(row["description"]) > 50:
        desc_words = set(_normalize(row["description"]).split())
        content_words = set(_normalize(text_sample).split())
        common = desc_words & content_words
        # Remove very common words
        common = {w for w in common if len(w) > 4}
        overlap = len(common) / max(len(desc_words), 1)
        if overlap < 0.05:
            flags["description_mismatch"] = {"overlap": round(overlap, 3)}

    # Store flags
    if not flags:
        confidence = "high"
    elif len(flags) >= 2:
        confidence = "low"
    else:
        confidence = "medium"
    validation = {"confidence": confidence, "flags": flags, "checks_run": 4}

    import json
    validation_json = json.dumps({"validation": validation})
    await execute(
        "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
        validation_json,
        UUID(book_id),
    )

    return validation


async def validate_batch(batch_size: int = 10) -> dict[str, Any]:
    """Validate a batch of books that have text profiles but no validation yet."""
    rows = await fetch_all("""
        SELECT b.id FROM books b
        WHERE b.extra_metadata ? 'incipit'
          AND NOT (b.extra_metadata ? 'validation')
        ORDER BY b.quality_score DESC
        LIMIT $1
    """, batch_size)

    validated = 0
    flagged = 0
    for r in rows:
        try:
            result = await validate_book(str(r["id"]))
            if result.get("flags"):
                flagged += 1
            validated += 1
        except Exception:
            continue

    return {"validated": validated, "flagged": flagged}
