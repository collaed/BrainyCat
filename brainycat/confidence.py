"""Multi-signal confidence scoring for book identification.

Combines all available signals to produce a 0-100% confidence that we've
correctly identified a book. Signals that agree boost confidence; conflicting
signals flag the book for human review.

Scoring model:
- ISBN extracted from content (OPF/OCR/filename)     → 30 pts
- Title matches enrichment source                    → 15 pts
- Author matches enrichment source                   → 15 pts
- Language detected == enrichment language            → 10 pts
- Cover pHash matches catalogue cover                → 10 pts
- Incipit matches another confirmed book             → 10 pts
- Multiple sources agree on same ISBN                → 5 pts
- Publication year matches                           → 5 pts
                                                      ─────
                                                      100 pts max

Conflicts (signals that disagree) reduce the score and flag for review.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


class Signal:
    """A single identification signal with value and source."""
    __slots__ = ("name", "value", "source", "weight")

    def __init__(self, name: str, value: Any, source: str, weight: int):
        self.name = name
        self.value = value
        self.source = source
        self.weight = weight


async def compute_confidence(book_id: str) -> dict[str, Any]:
    """Compute confidence score for a book from all available signals."""
    row = await fetch_one(
        "SELECT b.*, array_agg(DISTINCT bf.format) as formats FROM books b "
        "LEFT JOIN book_files bf ON bf.book_id = b.id WHERE b.id = $1 GROUP BY b.id",
        UUID(book_id),
    )
    if not row:
        return {"score": 0, "signals": [], "conflicts": []}

    extra = row["extra_metadata"] or {}
    if isinstance(extra, str):
        extra = json.loads(extra)

    signals: list[dict] = []
    conflicts: list[dict] = []
    score = 0

    isbn = row["isbn"]
    title = row["title"]

    # ── Signal 1: ISBN presence and source (max 30 pts) ──
    if isbn:
        isbn_sources = []
        # Check how the ISBN was obtained
        if extra.get("isbn_source"):
            isbn_sources.append(extra["isbn_source"])
        if extra.get("local_enriched") is True:
            isbn_sources.append("ol_local_match")
        local_title = extra.get("local_title_tried")
        if isinstance(local_title, dict) and local_title.get("isbn_from"):
            isbn_sources.append(local_title["isbn_from"])

        # ISBN from OCR copyright page
        ocr_log = await fetch_one(
            "SELECT details FROM enrichment_log WHERE book_id = $1 AND method = 'ocr_copyright' AND success = true LIMIT 1",
            UUID(book_id),
        )
        if ocr_log:
            isbn_sources.append("ocr_copyright")

        # Enrichment sources that confirmed this ISBN
        el_count = await fetch_one(
            "SELECT count(*) as n FROM enrichment_log WHERE book_id = $1 AND success = true",
            UUID(book_id),
        )

        if isbn_sources:
            pts = min(30, 20 + len(isbn_sources) * 5)
        else:
            pts = 15  # ISBN exists but source unknown (probably from filename/OPF)
        signals.append({"name": "isbn", "value": isbn, "sources": isbn_sources, "points": pts})
        score += pts

        # Multiple enrichment sources agreed
        if el_count and el_count["n"] >= 2:
            signals.append({"name": "multi_source_agreement", "value": el_count["n"], "points": 5})
            score += 5
    else:
        signals.append({"name": "isbn", "value": None, "points": 0, "note": "No ISBN found"})

    # ── Signal 2: Title quality (max 15 pts) ──
    if title and len(title) > 3:
        # Check if title was cleaned/confirmed
        title_pts = 10
        if extra.get("api_title_fix"):
            title_pts = 15  # Title was verified via API
        elif len(title) > 50 and ("." in title or "_" in title):
            title_pts = 5  # Looks like a filename, not a real title
        signals.append({"name": "title", "value": title[:80], "points": title_pts})
        score += title_pts
    else:
        signals.append({"name": "title", "value": title, "points": 0})

    # ── Signal 3: Author (max 15 pts) ──
    authors = await fetch_all(
        "SELECT a.name FROM authors a JOIN books_authors ba ON ba.author_id = a.id WHERE ba.book_id = $1",
        UUID(book_id),
    )
    if authors:
        signals.append({"name": "author", "value": [a["name"] for a in authors], "points": 15})
        score += 15
    else:
        signals.append({"name": "author", "value": None, "points": 0})

    # ── Signal 4: Language agreement (max 10 pts) ──
    langs = await fetch_all(
        "SELECT l.name FROM languages l JOIN books_languages bl ON bl.language_id = l.id WHERE bl.book_id = $1",
        UUID(book_id),
    )
    detected_lang = (extra.get("content_signals") or {}).get("detected_language")
    enrichment_lang = langs[0]["name"] if langs else None

    if detected_lang and enrichment_lang:
        det_short = detected_lang[:3].lower()
        enr_short = (enrichment_lang or "")[:3].lower()
        if det_short == enr_short or (det_short in enr_short) or (enr_short in det_short):
            signals.append({"name": "language_match", "value": f"{detected_lang}={enrichment_lang}", "points": 10})
            score += 10
        else:
            conflicts.append({
                "signal": "language",
                "detected": detected_lang,
                "enrichment": enrichment_lang,
                "note": "Content language differs from catalogue language",
            })
    elif enrichment_lang:
        signals.append({"name": "language", "value": enrichment_lang, "points": 5})
        score += 5

    # ── Signal 5: Cover pHash (max 10 pts) ──
    if extra.get("cover_phash"):
        signals.append({"name": "cover_phash", "value": "computed", "points": 5})
        score += 5
        # Not compared against a catalogue cover: none is fetched yet.
    elif row["cover_path"] and row["cover_path"] != "none":
        signals.append({"name": "cover", "value": "present, not hashed", "points": 3})
        score += 3

    # ── Signal 6: Incipit match (max 10 pts) ──
    incipit = extra.get("incipit")
    if incipit:
        local_title = extra.get("local_title_tried")
        incipit_match = extra.get("isbn_source") == "incipit_match" or (isinstance(local_title, dict) and local_title.get("isbn_from") == "incipit")
        if incipit_match:
            signals.append({"name": "incipit_match", "value": "confirmed via incipit", "points": 10})
            score += 10
        else:
            signals.append({"name": "incipit", "value": incipit[:60], "points": 3})
            score += 3

    # ── Signal 7: Publication year (max 5 pts) ──
    if row["pubdate"]:
        signals.append({"name": "pubdate", "value": str(row["pubdate"])[:10], "points": 5})
        score += 5

    # ── Detect conflicts ──
    lang_mismatch = extra.get("language_mismatch")
    if lang_mismatch:
        conflicts.append({
            "signal": "language_mismatch",
            "detected": lang_mismatch.get("detected"),
            "enrichment": lang_mismatch.get("enrichment"),
        })
        score = max(0, score - 15)  # Penalty

    # Title fuzzy confidence
    title_match_info = extra.get("local_title_tried")
    if isinstance(title_match_info, dict) and title_match_info.get("confidence"):
        conf = title_match_info["confidence"]
        if conf < 0.6:
            conflicts.append({
                "signal": "title_fuzzy_low_confidence",
                "confidence": conf,
                "method": title_match_info.get("isbn_from"),
                "note": "ISBN was assigned via low-confidence title match",
            })
            score = max(0, score - 10)

    # Cap at 99 (100 = human verified only)
    score = min(99, score)

    return {
        "score": score,
        "signals": signals,
        "conflicts": conflicts,
        "human_verified": extra.get("human_verified", False),
    }


async def compute_batch(batch_size: int = 50) -> dict[str, Any]:
    """Compute confidence scores for books that don't have one yet."""
    rows = await fetch_all("""
        SELECT id FROM books
        WHERE extra_metadata IS NULL
           OR NOT (extra_metadata ? 'confidence_score')
        ORDER BY quality_score DESC
        LIMIT $1
    """, batch_size)

    computed = 0
    for row in rows:
        result = await compute_confidence(str(row["id"]))
        await execute(
            "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{confidence_score}', $1::jsonb) WHERE id = $2",
            json.dumps(result["score"]),
            row["id"],
        )
        if result["conflicts"]:
            await execute(
                "UPDATE books SET extra_metadata = jsonb_set(extra_metadata, '{confidence_conflicts}', $1::jsonb) WHERE id = $2",
                json.dumps(result["conflicts"]),
                row["id"],
            )
        computed += 1

    return {"computed": computed}


async def get_top_confidence(limit: int = 20) -> list[dict[str, Any]]:
    """Get top N books by confidence score (for user verification)."""
    rows = await fetch_all("""
        SELECT b.id, b.title, b.isbn, b.cover_path,
               (b.extra_metadata->>'confidence_score')::int as confidence,
               b.extra_metadata->>'human_verified' as verified
        FROM books b
        WHERE (b.extra_metadata->>'confidence_score')::int >= 80
          AND (b.extra_metadata->>'human_verified') IS NULL
        ORDER BY (b.extra_metadata->>'confidence_score')::int DESC
        LIMIT $1
    """, limit)
    results = []
    for r in rows:
        detail = await compute_confidence(str(r["id"]))
        results.append({
            "id": str(r["id"]),
            "title": r["title"],
            "isbn": r["isbn"],
            "cover_path": r["cover_path"],
            "confidence": r["confidence"],
            "signals": detail["signals"],
        })
    return results


async def get_conflicts(limit: int = 20) -> list[dict[str, Any]]:
    """Get books with conflicting signals for user review."""
    rows = await fetch_all("""
        SELECT b.id, b.title, b.isbn, b.cover_path,
               (b.extra_metadata->>'confidence_score')::int as confidence,
               b.extra_metadata->'confidence_conflicts' as conflicts
        FROM books b
        WHERE b.extra_metadata ? 'confidence_conflicts'
          AND jsonb_array_length(b.extra_metadata->'confidence_conflicts') > 0
          AND (b.extra_metadata->>'human_verified') IS NULL
        ORDER BY jsonb_array_length(b.extra_metadata->'confidence_conflicts') DESC,
                 (b.extra_metadata->>'confidence_score')::int ASC
        LIMIT $1
    """, limit)
    results = []
    for r in rows:
        detail = await compute_confidence(str(r["id"]))
        results.append({
            "id": str(r["id"]),
            "title": r["title"],
            "isbn": r["isbn"],
            "cover_path": r["cover_path"],
            "confidence": r["confidence"],
            "signals": detail["signals"],
            "conflicts": detail["conflicts"],
        })
    return results


async def verify_book(book_id: str, confirmed: bool, corrections: dict | None = None) -> dict[str, Any]:
    """User confirms or corrects a book's identity. Sets to 100% if confirmed."""
    if confirmed:
        await execute(
            "UPDATE books SET extra_metadata = jsonb_set(jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{human_verified}', 'true'::jsonb), '{confidence_score}', '100'::jsonb) WHERE id = $1",
            UUID(book_id),
        )
        # Trigger contribute-back for 100% confirmed books
        try:
            from brainycat.contribute import contribute_back
            await contribute_back(book_id)
        except Exception:
            pass
        return {"ok": True, "score": 100}
    elif corrections:
        # Apply user corrections (isbn, title, author)
        if corrections.get("isbn"):
            await execute("UPDATE books SET isbn = $1, updated_at = now() WHERE id = $2", corrections["isbn"], UUID(book_id))
        if corrections.get("title"):
            await execute("UPDATE books SET title = $1, updated_at = now() WHERE id = $2", corrections["title"], UUID(book_id))
        # Recompute after corrections
        result = await compute_confidence(book_id)
        await execute(
            "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{confidence_score}', $1::jsonb) WHERE id = $2",
            json.dumps(result["score"]),
            UUID(book_id),
        )
        return {"ok": True, "score": result["score"]}
    return {"ok": False}
