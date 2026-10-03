"""Book fingerprinting — multi-phase duplicate/edition detection.

Phase 1: Structural fingerprint (chapter skeleton)
Phase 2: Winnowing algorithm (local text fingerprint)
Phase 3: Front matter edition detection

Stores compact fingerprints in DB for fast comparison via MinHash/LSH.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import zlib
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one

# Winnowing parameters
K = 25  # k-gram length
W = 4  # window size


# ── Text extraction ──────────────────────────────────────────────────────


def _extract_full_text(file_path: str, fmt: str) -> str:
    """Extract all plain text from an epub or pdf file. Internal helper used only by `_compute_sync`
    in this file."""
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
    """Lowercase and strip punctuation/extra whitespace before winnowing. Internal helper used only
    by `_text_fingerprint` in this file."""
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
    """Generate rolling hashes for k-grams.

    Uses zlib.crc32, not the builtin hash(): Python randomizes str hashing per process
    (PYTHONHASHSEED) unless disabled, so fingerprints computed before/after a restart would
    otherwise live in different, incomparable hash spaces and silently never match again.
    """
    if len(text) < k:
        return []
    return [zlib.crc32(text[i : i + k].encode()) for i in range(len(text) - k + 1)]


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


_MINHASH_MAX_INPUT = 50_000  # see _minhash docstring


def _minhash(fingerprint: list[int], num_hashes: int = 128) -> list[int]:
    """Compute MinHash signature for LSH comparison.

    Correctness/performance bug: this used to run `num_hashes` full passes over the *entire* winnowed
    fingerprint set with no size bound. For a real ~3.5M-character book that set has 1M+ elements —
    measured 53s of pure synchronous CPU time for one book's minhash alone (138M `hash((i, v))` calls,
    each allocating a tuple), inside an `async def` with no yield point, blocking the single-process
    event loop for the *entire* app for that whole duration. This is almost certainly the actual cause
    of the concurrent-load stalls seen throughout this project's test runs (see
    docs/ui-redesign/proposal.md, iterations 3-6).

    Fix is a bottom-k sketch, not an arbitrary truncation: dedupe, then keep the k smallest values by
    hash *value*. An earlier version of this fix sampled every Nth element by *position* in the input
    list instead — which silently broke actual cross-format duplicate detection (caught by
    test_cross_format_match_on_real_files): the same book extracted via two different pipelines
    produces two winnowed lists of different lengths with no shared positional indexing, so
    position-based sampling from each independently picks essentially unrelated subsets. A value-based
    bottom-k sketch doesn't have this problem — shared k-grams hash to the same values regardless of
    which pipeline produced them or where they land in either list, so the two books' bottom-k sets
    still overlap correctly, which is the entire property MinHash/Jaccard estimation depends on.
    """
    if not fingerprint:
        return []
    fp_set = set(fingerprint)
    if len(fp_set) > _MINHASH_MAX_INPUT:
        fp_set = set(sorted(fp_set)[:_MINHASH_MAX_INPUT])
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


def _compute_sync(file_path: str, fmt: str) -> dict[str, Any] | None:
    """The actual CPU-bound work (text extraction, winnowing, minhash), run off the event loop via
    asyncio.to_thread by the caller. Even with _minhash's own size cap, extraction+winnowing alone
    measured ~5s of sync CPU on a large real book — still enough to matter under concurrent load."""
    text = _extract_full_text(file_path, fmt)
    if len(text) < 1000:
        return None
    struct = _structural_fingerprint(text)
    winnowed = _text_fingerprint(text)
    minhash = _minhash(winnowed)
    edition = _edition_info(text)
    return {"struct": struct, "winnowed": winnowed, "minhash": minhash, "edition": edition, "text_len": len(text)}


async def compute_fingerprint(book_id: str) -> dict[str, Any]:
    """Compute and store all fingerprints for a book."""
    row = await fetch_one(
        "SELECT bf.file_path, bf.format FROM book_files bf WHERE bf.book_id = $1 AND bf.format IN ('epub','pdf') LIMIT 1",
        UUID(book_id),
    )
    if not row or not os.path.isfile(row["file_path"]):
        return {"ok": False, "reason": "no file"}

    result = await asyncio.to_thread(_compute_sync, row["file_path"], row["format"])
    if result is None:
        return {"ok": False, "reason": "too short"}

    struct = result["struct"]
    winnowed = result["winnowed"]
    minhash = result["minhash"]
    edition = result["edition"]
    text_len = result["text_len"]

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
        text_len,
    )
    return {"ok": True, "chapters": struct["chapter_count"], "fingerprint_size": len(winnowed), "edition": edition}


async def compare_fingerprints(book_id_a: str, book_id_b: str) -> float | None:
    """Jaccard similarity between two books' stored fingerprints (0..1), or None if either is missing.

    format_stack.verify_and_stack() has imported this name since it was written; it never existed,
    so every cross-format stacking attempt raised ImportError, silently swallowed by the scheduler's
    bare `except: pass`. Same skeleton hash (identical chapter boundaries) is treated as a strong
    match and floors the score at 0.8, mirroring find_duplicates_by_content's own rule.
    """
    rows = await fetch_all(
        "SELECT book_id, samples FROM book_fingerprints WHERE book_id = ANY($1)",
        [UUID(book_id_a), UUID(book_id_b)],
    )
    by_id = {str(r["book_id"]): r["samples"] for r in rows}
    sa, sb = by_id.get(book_id_a), by_id.get(book_id_b)
    if not sa or not sb or len(sa) < 2 or len(sb) < 2:
        return None
    try:
        minhash_a, minhash_b = json.loads(sa[1]), json.loads(sb[1])
    except (json.JSONDecodeError, IndexError):
        return None
    sim = _jaccard_minhash(minhash_a, minhash_b)
    if sa[0] and sa[0] == sb[0]:
        sim = max(sim, 0.8)
    return sim


async def compute_all_fingerprints(batch_size: int = 20) -> dict[str, Any]:
    """Compute fingerprints for a batch of un-fingerprinted books. Called every 20s by
    `scheduler._fingerprint_loop`."""
    rows = await fetch_all(
        """
        SELECT b.id FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
        ORDER BY (b.isbn IS NULL) DESC  -- prioritize books without ISBN
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
    """Compare content fingerprints (MinHash Jaccard) to populate the Content Duplicates review page.

    Called by: the scheduler's `_fingerprint_loop` (every 20s) and, on demand, the Intelligence →
    Content Duplicates page (`static/intel-content-dupes.html`). Writes candidate pairs into
    `duplicate_matches` for the human review queue.

    D1 fix: previously this had NO cursor — it re-sorted by title and processed only the first
    `batch_size` outer books every run, so any pair where both books sort after that position was
    never compared, and `_fingerprint_loop` re-scanned the same 20 books forever. It also computed a
    size ratio and threw it away. Now it advances a persisted cursor across runs and uses the size
    ratio to suppress obvious different-length false matches.
    """
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

    # D1: persisted cursor so successive runs sweep the whole list instead of re-scanning the head.
    cur_row = await fetch_one("SELECT value FROM app_settings WHERE key = 'dedup_cursor'")
    start = 0
    if cur_row:
        try:
            start = int(cur_row["value"]) % max(len(books), 1)
        except (ValueError, TypeError):
            start = 0

    new_matches = 0
    checked = 0
    i = start

    while checked < batch_size and checked < len(books):
        a = books[i]
        for b in books[i + 1 :]:
            # Quick filter: skeleton hash match = very likely same work
            same_skeleton = a["skeleton"] == b["skeleton"] and a["skeleton"]

            # MinHash Jaccard similarity
            sim = _jaccard_minhash(a["minhash"], b["minhash"])

            # Size similarity — now USED (D1): very different lengths are not the same content.
            size_ratio = (min(a["chars"], b["chars"]) / max(a["chars"], b["chars"])) if a["chars"] and b["chars"] else 0

            # Decision
            if (same_skeleton or sim > 0.3) and (same_skeleton or size_ratio >= 0.5):
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
        i = (i + 1) % len(books)

    # D1: persist where to resume next run (app_settings.value is JSONB).
    await execute(
        "INSERT INTO app_settings (key, value) VALUES ('dedup_cursor', to_jsonb($1::int)) "
        "ON CONFLICT (key) DO UPDATE SET value = to_jsonb($1::int)",
        i,
    )

    total_matches = await fetch_one("SELECT count(*) as n FROM duplicate_matches WHERE status='pending'")
    return {"new_matches": new_matches, "total_pending": total_matches["n"] if total_matches else 0}


# Formats that carry real, selectable text — as opposed to a PDF that's just page-scan images.
_TEXT_FORMATS = {"epub", "mobi", "azw3", "fb2", "txt"}
# Below this text-density (chars per KB of file size), a PDF's fingerprint sample is basically
# nothing — the empirical distribution across this library's fingerprinted PDFs has p10 ≈ 9.3
# chars/KB and a handful of clear outliers under 2, so 3 sits comfortably between "no OCR text
# layer" and "genuinely short/sparse but real text."
_LOSSY_CHARS_PER_KB = 3.0


def _side_profile(formats: list[str] | None, total_size: int | None, total_chars: int | None) -> dict[str, Any]:
    """Summarize one side of a duplicate pair (formats, size, whether it's a lossy scanned PDF).
    Internal helper used only by `get_duplicate_matches` in this file."""
    formats = formats or []
    has_text_format = bool(_TEXT_FORMATS & set(formats))
    chars_per_kb = (total_chars / (total_size / 1000)) if total_chars and total_size else None
    # Lossy: no epub/mobi/etc, and either no fingerprint yet or a suspiciously text-sparse PDF.
    is_lossy = not has_text_format and "pdf" in formats and (chars_per_kb is None or chars_per_kb < _LOSSY_CHARS_PER_KB)
    return {
        "formats": formats,
        "size": total_size or 0,
        "has_text_format": has_text_format,
        "is_lossy": is_lossy,
    }


def _recommend(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, int]:
    """Pick which side to keep: prefer real text over a lossy scan, then more formats, then the
    larger file (usually the more complete/higher-quality copy). Returns (keep, space_saved_bytes)."""
    if a["is_lossy"] != b["is_lossy"]:
        keep = "a" if b["is_lossy"] else "b"
    elif len(a["formats"]) != len(b["formats"]):
        keep = "a" if len(a["formats"]) > len(b["formats"]) else "b"
    else:
        keep = "a" if a["size"] >= b["size"] else "b"
    drop = b if keep == "a" else a
    return keep, drop["size"]


async def get_duplicate_matches() -> list[dict[str, Any]]:
    """List pending content-duplicate matches with keep/drop recommendations. Called by
    `GET /api/v1/fingerprints/matches` in routes/enrichment.py, used by static/intel-content-dupes.html."""
    rows = await fetch_all("""
        SELECT dm.*, ba.title as title_a, bb.title as title_b,
               array_agg(DISTINCT aa.name) FILTER (WHERE aa.name IS NOT NULL) as authors_a,
               array_agg(DISTINCT ab.name) FILTER (WHERE ab.name IS NOT NULL) as authors_b,
               array_agg(DISTINCT bfa.format) FILTER (WHERE bfa.format IS NOT NULL) as formats_a,
               array_agg(DISTINCT bfb.format) FILTER (WHERE bfb.format IS NOT NULL) as formats_b,
               sum(DISTINCT bfa.file_size) as size_a_raw,
               sum(DISTINCT bfb.file_size) as size_b_raw,
               max(fpa.total_chars) as chars_a,
               max(fpb.total_chars) as chars_b
        FROM duplicate_matches dm
        JOIN books ba ON ba.id = dm.book_a_id JOIN books bb ON bb.id = dm.book_b_id
        LEFT JOIN books_authors baa ON baa.book_id = dm.book_a_id LEFT JOIN authors aa ON aa.id = baa.author_id
        LEFT JOIN books_authors bab ON bab.book_id = dm.book_b_id LEFT JOIN authors ab ON ab.id = bab.author_id
        LEFT JOIN book_files bfa ON bfa.book_id = dm.book_a_id
        LEFT JOIN book_files bfb ON bfb.book_id = dm.book_b_id
        LEFT JOIN book_fingerprints fpa ON fpa.book_id = dm.book_a_id
        LEFT JOIN book_fingerprints fpb ON fpb.book_id = dm.book_b_id
        WHERE dm.status = 'pending'
        GROUP BY dm.id, ba.title, bb.title
        ORDER BY dm.overlap_pct DESC
    """)
    # NOTE: size_a/size_b use `sum(DISTINCT ...)` above to avoid fanout double-counting from the
    # book_files join crossed with the authors join — fine as long as a book's files don't share
    # an exact file_size (astronomically unlikely for real ebook files).
    matches = []
    for r in rows:
        side_a = _side_profile(r["formats_a"], r["size_a_raw"], r["chars_a"])
        side_b = _side_profile(r["formats_b"], r["size_b_raw"], r["chars_b"])
        keep, space_saved = _recommend(side_a, side_b)

        if side_a["is_lossy"] != side_b["is_lossy"]:
            lossy_side, text_side = ("A", "B") if side_a["is_lossy"] else ("B", "A")
            reco = f"Keep {text_side} (has real text) — {lossy_side} looks like a scanned PDF with no text layer"
        elif keep == "a":
            reco = "Keep A — more complete/larger copy" if side_a["size"] >= side_b["size"] else "Keep A"
        else:
            reco = "Keep B — more complete/larger copy" if side_b["size"] >= side_a["size"] else "Keep B"

        matches.append(
            {
                "id": str(r["id"]),
                "book_a": str(r["book_a_id"]),
                "title_a": r["title_a"],
                "authors_a": r["authors_a"] or [],
                "formats_a": side_a["formats"],
                "size_a": side_a["size"],
                "is_lossy_a": side_a["is_lossy"],
                "book_b": str(r["book_b_id"]),
                "title_b": r["title_b"],
                "authors_b": r["authors_b"] or [],
                "formats_b": side_b["formats"],
                "size_b": side_b["size"],
                "is_lossy_b": side_b["is_lossy"],
                "overlap_pct": round(r["overlap_pct"], 1),
                "matching_samples": r["matching_samples"],
                "total_samples": r["total_samples"],
                "recommended_keep": keep,
                "recommendation": reco,
                "space_saved_bytes": space_saved,
            }
        )
    return matches


async def resolve_match(match_id: str, action: str) -> dict[str, bool]:
    """Mark a duplicate match resolved (e.g. merged/dismissed). Called by the resolve endpoint in
    routes/enrichment.py, used by static/intel-content-dupes.html."""
    await execute("UPDATE duplicate_matches SET status = $1 WHERE id = $2", action, UUID(match_id))
    return {"ok": True}


async def find_exact_duplicates() -> list[dict[str, Any]]:
    """Find exact file duplicates via file size pre-filter + hash comparison.

    O(n) pre-filter by file size, then MD5 only for same-size files.
    Inspired by Calibre's Find Duplicates binary compare algorithm.
    """
    import hashlib

    from brainycat.db import fetch_all

    # Group files by size
    rows = await fetch_all("""
        SELECT bf.book_id, bf.file_path, bf.file_size, b.title
        FROM book_files bf JOIN books b ON b.id = bf.book_id
        WHERE bf.file_size > 0
        ORDER BY bf.file_size
    """)

    # Group by file_size
    size_groups: dict[int, list[dict]] = {}
    for r in rows:
        size = r["file_size"] or 0
        if size > 0:
            size_groups.setdefault(size, []).append(dict(r))

    # Only check groups with >1 file (same size = potential duplicate)
    duplicates = []
    for size, files in size_groups.items():
        if len(files) < 2:
            continue
        # Hash each file
        hashes: dict[str, list[dict]] = {}
        for f in files:
            try:
                import os

                if os.path.isfile(f["file_path"]):
                    with open(f["file_path"], "rb") as fh:
                        h = hashlib.md5(fh.read(1024 * 1024)).hexdigest()  # First 1MB
                    hashes.setdefault(h, []).append(f)
            except Exception:
                pass
        for h, group in hashes.items():
            if len(group) > 1:
                duplicates.append(
                    {
                        "hash": h,
                        "file_size": size,
                        "books": [{"id": str(g["book_id"]), "title": g["title"]} for g in group],
                    }
                )

    return duplicates


async def quick_simhash(file_path: str) -> dict[str, Any] | None:
    """Quick SimHash of first 1000 words for instant dedup on upload."""
    import hashlib
    import os

    ext = os.path.splitext(file_path)[1].lower()
    text = ""

    try:
        if ext == ".epub":
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            book = epub.read_epub(file_path, options={"ignore_ncx": True})
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text += soup.get_text() + " "
                if len(text.split()) > 1200:
                    break
        elif ext == ".pdf":
            import fitz

            doc = fitz.open(file_path)
            for i in range(min(10, len(doc))):
                text += doc[i].get_text() + " "
                if len(text.split()) > 1200:
                    break
            doc.close()
    except Exception:
        return None

    words = text.split()[:1000]
    if len(words) < 100:
        return None

    # Generate SimHash: hash each 5-word shingle, combine
    shingles = [" ".join(words[i : i + 5]) for i in range(len(words) - 4)]
    hash_bits = [int(hashlib.md5(s.encode()).hexdigest(), 16) for s in shingles[:200]]

    # Simple 64-bit SimHash
    v = [0] * 64
    for h in hash_bits:
        for i in range(64):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    simhash = sum(1 << i for i in range(64) if v[i] > 0)

    # Check against existing books (hamming distance < 5 = likely same content)
    # For now, just return the hash — full comparison needs a simhash column
    return {"simhash": simhash, "words_sampled": len(words)}
