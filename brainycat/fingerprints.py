"""Book fingerprinting — multi-phase duplicate/edition detection.

Phase 1: Structural fingerprint (chapter skeleton)
Phase 2: Winnowing algorithm (local text fingerprint)
Phase 3: Front matter edition detection

Stores compact fingerprints in DB for fast comparison via MinHash/LSH.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one

# Winnowing parameters
K = 25  # k-gram length
W = 4  # window size


# ── Text extraction ──────────────────────────────────────────────────────


def _extract_full_text(file_path: str, fmt: str) -> str:
    try:
        if fmt == "epub":
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            book = epub.read_epub(file_path, options={"ignore_ncx": True})
            parts = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                parts.append(soup.get_text(separator="\n", strip=True))
            return "\n".join(parts)
        if fmt == "pdf":
            import fitz

            doc = fitz.open(file_path)
            parts = [page.get_text() for page in doc]
            doc.close()
            return "\n".join(parts)
    except Exception:
        pass
    return ""


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Phase 1: Structural fingerprint ─────────────────────────────────────


def _structural_fingerprint(text: str) -> dict[str, Any]:
    """Extract chapter skeleton: first/last 50 words of each chapter."""
    # Detect chapter boundaries
    chapters = re.split(
        r"\n\s*(?:chapter|chapitre|part|partie|section)\s+[\divxlc]+[.\s:—-]*",
        text,
        flags=re.IGNORECASE,
    )
    if len(chapters) < 2:
        # Try numbered headings
        chapters = re.split(r"\n\s*\d+[.\s]+[A-Z]", text)
    if len(chapters) < 2:
        chapters = [text]

    anchors = []
    for ch in chapters:
        words = ch.split()
        if len(words) < 20:
            continue
        first50 = " ".join(words[:50])
        last50 = " ".join(words[-50:])
        anchors.append(hashlib.md5((first50 + "|" + last50).encode()).hexdigest()[:12])

    combined = hashlib.md5("|".join(anchors).encode()).hexdigest()
    return {"chapter_count": len(anchors), "anchors": anchors, "skeleton_hash": combined}


# ── Phase 2: Winnowing ──────────────────────────────────────────────────


def _kgram_hashes(text: str, k: int = K) -> list[int]:
    """Generate rolling hashes for k-grams."""
    if len(text) < k:
        return []
    return [hash(text[i : i + k]) for i in range(len(text) - k + 1)]


def _winnow(hashes: list[int], w: int = W) -> list[int]:
    """Winnowing: keep minimum hash per window → sparse fingerprint."""
    if len(hashes) < w:
        return hashes
    fingerprint = []
    prev_min_idx = -1
    for i in range(len(hashes) - w + 1):
        window = hashes[i : i + w]
        min_val = min(window)
        min_idx = i + window.index(min_val)
        if min_idx != prev_min_idx:
            fingerprint.append(min_val)
            prev_min_idx = min_idx
    return fingerprint


def _text_fingerprint(text: str) -> list[int]:
    """Full winnowing fingerprint of normalized text."""
    norm = _normalize(text)
    # Skip first/last 10% (front/back matter)
    start = int(len(norm) * 0.1)
    end = int(len(norm) * 0.9)
    body = norm[start:end]
    if len(body) < K * 2:
        return []
    hashes = _kgram_hashes(body)
    return _winnow(hashes)


# ── Phase 3: Front matter edition detection ──────────────────────────────


def _edition_info(text: str) -> dict[str, Any]:
    """Extract edition markers from front matter."""
    front = text[:5000]
    info: dict[str, Any] = {}

    # Number line: "10 9 8 7 6 5 4 3 2 1"
    m = re.search(r"(\d+\s+)+\d+\s*$", front, re.MULTILINE)
    if m:
        nums = [int(x) for x in m.group().split()]
        if len(nums) >= 3 and nums == sorted(nums, reverse=True):
            info["printing"] = min(nums)

    # Edition statement
    m = re.search(r"(first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+edition", front, re.IGNORECASE)
    if m:
        info["edition"] = m.group()

    m = re.search(r"(revised|updated|enlarged|expanded)\s+edition", front, re.IGNORECASE)
    if m:
        info["revision"] = m.group()

    return info


# ── MinHash for fast comparison ──────────────────────────────────────────


def _minhash(fingerprint: list[int], num_hashes: int = 128) -> list[int]:
    """Compute MinHash signature for LSH comparison."""
    if not fingerprint:
        return []
    fp_set = set(fingerprint)
    signature = []
    for i in range(num_hashes):
        min_h = min((hash((i, v)) for v in fp_set), default=0)
        signature.append(min_h)
    return signature


def _jaccard_minhash(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimate Jaccard similarity from MinHash signatures."""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b, strict=False) if a == b)
    return matches / len(sig_a)


# ── Compute & store ─────────────────────────────────────────────────────


async def compute_fingerprint(book_id: str) -> dict[str, Any]:
    """Compute and store all fingerprints for a book."""
    row = await fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf WHERE bf.book_id = $1 AND bf.format IN ('epub','pdf') LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"ok": False, "reason": "no file"}

    text = _extract_full_text(row["file_path"], row["format"])
    if len(text) < 1000:
        return {"ok": False, "reason": "too short"}

    struct = _structural_fingerprint(text)
    winnowed = _text_fingerprint(text)
    minhash = _minhash(winnowed)
    edition = _edition_info(text)

    import json

    await execute(
        """INSERT INTO book_fingerprints (book_id, samples, sample_count, total_chars, computed_at)
           VALUES ($1, $2, $3, $4, now())
           ON CONFLICT (book_id) DO UPDATE SET samples = $2, sample_count = $3, total_chars = $4, computed_at = now()""",
        UUID(book_id),
        # Store: skeleton_hash, minhash (as hex strings), edition info, chapter count
        [
            struct["skeleton_hash"],
            json.dumps(minhash[:64]),  # store 64 minhash values as JSON string
            json.dumps(struct["anchors"][:20]),
            json.dumps(edition),
        ],
        len(minhash),
        len(text),
    )
    return {"ok": True, "chapters": struct["chapter_count"], "fingerprint_size": len(winnowed), "edition": edition}


async def compute_all_fingerprints(batch_size: int = 20) -> dict[str, Any]:
    rows = await fetch_all(
        """
        SELECT b.id FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
        LIMIT $1
    """,
        batch_size,
    )
    computed = 0
    for r in rows:
        result = await compute_fingerprint(str(r["id"]))
        if result.get("ok"):
            computed += 1
    total = await fetch_one("SELECT count(*) as n FROM book_fingerprints")
    pending = await fetch_one("""
        SELECT count(*) as n FROM books b JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
    """)
    return {"computed": computed, "total_fingerprinted": total["n"] if total else 0, "pending": pending["n"] if pending else 0}


async def find_duplicates_by_content(batch_size: int = 50) -> dict[str, Any]:
    """Compare fingerprints using MinHash Jaccard similarity."""
    import json

    rows = await fetch_all("""
        SELECT fp.book_id, fp.samples, fp.total_chars, b.title
        FROM book_fingerprints fp JOIN books b ON b.id = fp.book_id
        WHERE fp.sample_count > 0
        ORDER BY b.title
    """)

    books = []
    for r in rows:
        samples = r["samples"] or []
        if len(samples) < 2:
            continue
        try:
            minhash = json.loads(samples[1]) if len(samples) > 1 else []
            skeleton = samples[0] if samples else ""
        except (json.JSONDecodeError, IndexError):
            continue
        books.append({"id": r["book_id"], "title": r["title"], "skeleton": skeleton, "minhash": minhash, "chars": r["total_chars"]})

    new_matches = 0
    checked = 0

    for i, a in enumerate(books):
        if checked >= batch_size:
            break
        for b in books[i + 1 :]:
            # Quick filter: skeleton hash match = very likely same work
            same_skeleton = a["skeleton"] == b["skeleton"] and a["skeleton"]

            # MinHash Jaccard similarity
            sim = _jaccard_minhash(a["minhash"], b["minhash"])

            # Size similarity (within 10%)
            min(a["chars"], b["chars"]) / max(a["chars"], b["chars"]) if a["chars"] and b["chars"] else 0

            # Decision
            if same_skeleton or sim > 0.3:
                overlap = sim * 100
                if same_skeleton:
                    overlap = max(overlap, 80)

                existing = await fetch_one(
                    "SELECT id FROM duplicate_matches WHERE (book_a_id=$1 AND book_b_id=$2) OR (book_a_id=$2 AND book_b_id=$1)",
                    a["id"],
                    b["id"],
                )
                if existing:
                    continue

                await execute(
                    """INSERT INTO duplicate_matches (book_a_id, book_b_id, overlap_pct, matching_samples, total_samples)
                       VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""",
                    a["id"],
                    b["id"],
                    overlap,
                    1 if same_skeleton else 0,
                    len(a["minhash"]),
                )
                new_matches += 1
        checked += 1

    total_matches = await fetch_one("SELECT count(*) as n FROM duplicate_matches WHERE status='pending'")
    return {"new_matches": new_matches, "total_pending": total_matches["n"] if total_matches else 0}


async def get_duplicate_matches() -> list[dict[str, Any]]:
    rows = await fetch_all("""
        SELECT dm.*, ba.title as title_a, bb.title as title_b,
               array_agg(DISTINCT aa.name) FILTER (WHERE aa.name IS NOT NULL) as authors_a,
               array_agg(DISTINCT ab.name) FILTER (WHERE ab.name IS NOT NULL) as authors_b
        FROM duplicate_matches dm
        JOIN books ba ON ba.id = dm.book_a_id JOIN books bb ON bb.id = dm.book_b_id
        LEFT JOIN books_authors baa ON baa.book_id = dm.book_a_id LEFT JOIN authors aa ON aa.id = baa.author_id
        LEFT JOIN books_authors bab ON bab.book_id = dm.book_b_id LEFT JOIN authors ab ON ab.id = bab.author_id
        WHERE dm.status = 'pending'
        GROUP BY dm.id, ba.title, bb.title
        ORDER BY dm.overlap_pct DESC
    """)
    return [
        {
            "id": str(r["id"]),
            "book_a": str(r["book_a_id"]),
            "title_a": r["title_a"],
            "authors_a": r["authors_a"] or [],
            "book_b": str(r["book_b_id"]),
            "title_b": r["title_b"],
            "authors_b": r["authors_b"] or [],
            "overlap_pct": round(r["overlap_pct"], 1),
            "matching_samples": r["matching_samples"],
            "total_samples": r["total_samples"],
        }
        for r in rows
    ]


async def resolve_match(match_id: str, action: str) -> dict[str, bool]:
    await execute("UPDATE duplicate_matches SET status = $1 WHERE id = $2", action, UUID(match_id))
    return {"ok": True}
