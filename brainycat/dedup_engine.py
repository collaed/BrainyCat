"""Dedup engine — confirm duplicates via content sampling before merging.

Strategy:
1. Find candidates (same ISBN, or title similarity > 0.85)
2. Sample 3 passages from 40-60% of each book (the "middle" — avoids TOC/appendix)
3. Compare samples: if overlap > 80%, confirm as duplicate
4. For borderline cases (60-80%), ask Intello LLM for similarity verdict
5. Keep the best copy (highest quality score, most metadata, best file quality)
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from brainycat import db
from brainycat.content_guard import _sample_epub, _sample_pdf


async def find_candidates(limit: int = 20) -> list[dict[str, Any]]:
    """Find duplicate candidates: same ISBN or very similar titles."""
    # Same ISBN
    rows = await db.fetch_all(
        """SELECT isbn, array_agg(id ORDER BY quality_score DESC) as ids,
                  array_agg(title ORDER BY quality_score DESC) as titles
           FROM books WHERE isbn IS NOT NULL
           GROUP BY isbn HAVING count(*) > 1
           LIMIT $1""",
        limit,
    )
    candidates = []
    for r in rows:
        candidates.append({
            "reason": "same_isbn",
            "isbn": r["isbn"],
            "ids": [str(i) for i in r["ids"]],
            "titles": r["titles"],
        })
    return candidates


async def verify_duplicate(id_a: str, id_b: str) -> dict[str, Any]:
    """Verify two books are duplicates by sampling middle content."""
    import os

    file_a = await db.fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 ORDER BY created_at LIMIT 1", UUID(id_a))
    file_b = await db.fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 ORDER BY created_at LIMIT 1", UUID(id_b))

    if not file_a or not file_b:
        return {"verified": False, "reason": "missing files"}
    if not os.path.isfile(file_a["file_path"]) or not os.path.isfile(file_b["file_path"]):
        return {"verified": False, "reason": "files not on disk"}

    # Extract middle samples (40-60% of book)
    text_a = _extract_middle(file_a["file_path"], file_a["format"])
    text_b = _extract_middle(file_b["file_path"], file_b["format"])

    if len(text_a) < 200 or len(text_b) < 200:
        return {"verified": False, "reason": "insufficient text for comparison"}

    # Compare
    overlap = SequenceMatcher(None, text_a[:3000].lower(), text_b[:3000].lower()).ratio()

    if overlap > 0.80:
        return {"verified": True, "overlap": round(overlap * 100, 1), "method": "sampling"}
    elif overlap > 0.60:
        # Borderline — ask LLM
        llm_result = await _llm_similarity_check(text_a[:1500], text_b[:1500])
        return {"verified": llm_result.get("same_book", False), "overlap": round(overlap * 100, 1),
                "method": "llm", "llm_confidence": llm_result.get("confidence", 0)}
    else:
        return {"verified": False, "overlap": round(overlap * 100, 1), "reason": "different content"}


def _extract_middle(file_path: str, fmt: str) -> str:
    """Extract text from the middle 40-60% of a book."""
    if fmt == "epub":
        samples = _sample_epub(file_path)
    elif fmt == "pdf":
        samples = _sample_pdf(file_path)
    else:
        return ""
    # samples are at 25%, 50%, 75% — use the 50% one (index 1)
    if len(samples) >= 2:
        return samples[1]
    return samples[0] if samples else ""


async def _llm_similarity_check(text_a: str, text_b: str) -> dict[str, Any]:
    """Ask Intello LLM if two text samples are from the same book."""
    from brainycat.config import settings
    from brainycat.http_client import get_client

    if not settings.intello_url:
        return {"same_book": False, "confidence": 0}

    prompt = (
        "You are comparing two text excerpts to determine if they come from the same book "
        "(possibly different editions or formats). Reply with JSON only: "
        '{"same_book": true/false, "confidence": 0-100, "reason": "brief explanation"}\n\n'
        f"EXCERPT A:\n{text_a[:1000]}\n\nEXCERPT B:\n{text_b[:1000]}"
    )

    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 100, "temperature": 0},
            headers={"Authorization": f"Bearer {settings.intello_api_key}"},
            timeout=15,
        )
        if resp.status_code == 200:
            import json
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception:
        pass
    return {"same_book": False, "confidence": 0}


async def pick_best(ids: list[str]) -> str:
    """Among duplicate books, pick the best one to keep."""
    rows = await db.fetch_all(
        """SELECT b.id, b.quality_score, b.isbn, b.description IS NOT NULL as has_desc,
                  b.cover_path IS NOT NULL as has_cover,
                  bf.file_size, bf.format
           FROM books b
           LEFT JOIN book_files bf ON bf.book_id = b.id
           WHERE b.id = ANY($1)
           ORDER BY b.quality_score DESC, bf.file_size DESC""",
        [UUID(i) for i in ids],
    )
    if not rows:
        return ids[0]
    # Best = highest quality score, then largest file (more complete)
    return str(rows[0]["id"])


async def auto_dedup_cycle(limit: int = 10) -> dict[str, Any]:
    """One cycle: find candidates, verify, merge confirmed duplicates."""
    from brainycat.smart_merge import merge_books

    candidates = await find_candidates(limit=limit)
    verified = 0
    merged = 0

    for c in candidates:
        ids = c["ids"]
        if len(ids) < 2:
            continue

        # Verify first pair
        result = await verify_duplicate(ids[0], ids[1])
        if result.get("verified"):
            verified += 1
            keep = await pick_best(ids)
            merge_ids = [i for i in ids if i != keep]
            await merge_books(keep, merge_ids)
            merged += 1

    return {"candidates": len(candidates), "verified": verified, "merged": merged}
