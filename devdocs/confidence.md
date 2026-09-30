# Confidence Scoring

## Purpose

Not all enrichment is correct. If you search "The Art" on Google Books, you might get "The Art of War" for a book that's actually "The Art of Electronics." The confidence scorer evaluates how sure we are that the enrichment metadata actually belongs to this book.

## The 7 Signals

| # | Signal | Max pts | How scored |
|---|--------|---------|-----------|
| 1 | ISBN presence + provenance | 30 | 20 base + 5 per confirming source (max 30) |
| 2 | Multi-source agreement | 5 | ≥2 enrichment sources confirmed same data |
| 3 | Title quality | 15 | 15 if API-verified, 10 if clean, 5 if filename-like |
| 4 | Author present | 15 | Has author in books_authors table |
| 5 | Language agreement | 10 / -15 | +10 if detected == enrichment; -15 penalty if mismatch |
| 6 | Cover pHash | 5-10 | 5 if computed, 10 if matches catalogue cover |
| 7 | Incipit match | 3-10 | 10 if confirmed via opening-text linking, 3 if incipit extracted |
| 8 | Publication date | 5 | Date is set |

**Cap:** Auto-scored books max at 99. Only human verification reaches 100.

**Penalty triggers:**
- Language mismatch (detected vs enrichment disagree): -15 pts
- Low-confidence title match (fuzzy < 0.6): -10 pts

## Current Status (2026-06-06)

- **Loop status:** ✅ Fixed and running — 50 books per tick, every 60s
- **Progress:** 5,315 books scored (out of 63,502)
- **Rate:** ~2,000/day
- **Bug fixed:** 2026-06-05 (see below)

## The Bug (FIXED)

**Symptom:** `'bool' object has no attribute 'get'` every 60s.

**Root cause:** 13,209 books had `extra_metadata.local_title_tried = true` (a JSON boolean). In Signal 6 (incipit match), the code did:

```python
# BROKEN (before fix):
incipit_match = extra.get("isbn_source") == "incipit_match" or extra.get("local_title_tried", {}).get("isbn_from") == "incipit"
```

When `local_title_tried` is `True`, `extra.get("local_title_tried", {})` returns `True` (not the default `{}`), then `.get("isbn_from")` crashes because `bool` has no `.get()`.

**Fix applied 2026-06-05:**
```python
# FIXED:
local_title = extra.get("local_title_tried")
incipit_match = extra.get("isbn_source") == "incipit_match" or (isinstance(local_title, dict) and local_title.get("isbn_from") == "incipit")
```

Other code paths already had `isinstance` guards (Signal 1 at line 70, conflict detection at line 151).

## Batch Processing

`compute_batch(batch_size=50)`:
1. Finds 50 books without `confidence_score` in `extra_metadata`
2. Calls `compute_confidence(book_id)` for each
3. Stores score in `extra_metadata.confidence_score`
4. If conflicts found, stores in `extra_metadata.confidence_conflicts`

Processes `ORDER BY quality_score DESC` — highest-quality books first.

## Human Verification

The `/static/verify.html` page shows high-confidence books for manual confirmation:
- `GET /api/v1/confidence/top` → books scoring ≥80, not yet verified
- `GET /api/v1/confidence/conflicts` → books with conflicting signals
- `POST /api/v1/confidence/verify` → user confirms or corrects

On confirmation: score = 100, `human_verified = true`. If the book has ISBN, contributes back to Open Library.

## Quality Score vs Confidence Score

| Metric | quality_score | confidence_score |
|--------|--------------|-----------------|
| Stored in | `books.quality_score` column | `extra_metadata.confidence_score` |
| Measures | Metadata completeness | Identity correctness |
| Range | 0-100 | 0-100 |
| Example | Has ISBN, cover, desc, author = 80 | Low fuzzy match, no ISBN = 30 |
| Max | 100 (all fields filled) | 99 auto, 100 human-verified |

A book can have quality 80 (lots of metadata) but confidence 30 (might be wrong book).
