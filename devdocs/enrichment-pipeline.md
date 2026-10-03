# Enrichment Pipeline

## Architecture (2026-06-06)

Four tiers, progressively more expensive:

```
Tier 0: ISBN Extraction   → file I/O, no network  → ~112 ISBNs/day
Tier 1: Local SQLite      → instant, no network   → ~1000 books/min
Tier 2: OL Works API      → 1 targeted GET/book   → ~420/hour
Tier 3: Full API sources  → rate-limited, parallel → ~3 books/min (when unbanned)
```

## Current Throughput

| Tier | Loop | Status | Rate |
|------|------|--------|------|
| 0 | isbn_extract | ✅ Running | Dedicated thread, no pacing, ~4-10 books/min |
| 1 | fast_local_isbn | ✅ Running | 5-14 books/tick, self-fed by Tier 0 |
| 1 | fast_local_title | ✅ Running | 26/50 matches/batch, feeds ISBNs back |
| 2 | ol_works | ✅ Running | 3-6 descriptions/batch of 10, every 3s |
| 3 | enrichment | ⚠️ Timeouts | External APIs banned; AIMD will retry |
| 3 | google_books | ⚠️ Backed off | 429s; AIMD handles |

## Tier 0: ISBN Extraction (NEW)

**The bottleneck was always ISBNs.** 19,687 books had no ISBN — they can't be enriched via any source. The isbn_extract loop scans file content using 6 methods:

| Method | How | Hit rate |
|--------|-----|----------|
| OPF metadata | Dublin Core in EPUB's content.opf | High for commercial EPUBs |
| Full-text scan | Regex with multilingual anchors, type detection | High for modern books |
| PDF metadata | DocInfo Subject/Keywords/Comments | Medium |
| Filename | Pattern matching (ISBN in filename) | Medium |
| Barcode decode | EAN-13 via pyzbar on page images | Low (needs image) |
| OCR last page | Tesseract on copyright page | Fallback |

**Priority order:** OPF → PDF metadata → filename → full text → barcode → OCR. Stops at first valid ISBN found.

**Type detection:** Contextual keywords around ISBN identify type:
- "ebook", "epub", "numérique" → ebook ISBN (preferred)
- "pdf" → PDF ISBN
- "print", "paperback", "broché" → print ISBN
- "audio", "hörbuch" → audiobook ISBN

The pipeline selects the best ISBN by type priority: ebook > pdf > unknown > print > paperback > hardcover > audiobook.

## Tier 1: Local Enrichment

### Source Data

| Database | Records | Source | Coverage |
|----------|---------|--------|----------|
| isbn_lookup.db | ~30M | OL editions dump | Global, all languages |
| bnf_lookup.db | ~500K | BnF SPARQL | French books |
| title_lookup (table in isbn_lookup.db) | ~30M | Normalized titles | For reverse lookup |

### ISBN Pass (fast_local_isbn)

```
Book has ISBN → lookup in isbn_lookup.db → get:
  publisher, subjects, pubdate, pages, cover_id, ol_key, work_key
→ write to books table + books_publishers + books_tags
→ set extra_metadata.local_enriched = true
```

### Title Pass (fast_local_title)

For books WITHOUT ISBN:
```
Normalize title → 3-tier fuzzy match → assign ISBN if confident
→ set extra_metadata.local_title_tried = {isbn_from, confidence, ol_key}
   OR = true (if no match found — the bool values causing historical bugs)
```

**Self-feeding effect:** Every ISBN found by title matching immediately feeds into the ISBN pass, which enriches the book, which then feeds into OL Works for description.

## Tier 2: OL Works API (NEW)

**Key insight:** The local SQLite dump contains `work_key` for 94% of ISBN-matched books. This enables surgical enrichment without searching:

```
Book has local_enriched=true + no description + ISBN
→ Look up work_key from isbn_lookup.db
→ GET https://openlibrary.org/works/{key}.json
→ Extract: description, subjects, DDC
→ GET https://openlibrary.org/works/{key}/ratings.json
→ Extract: average rating
→ Write description + tags + rating
→ Mark extra_metadata.ol_works_tried
```

**Why this is efficient:**
- One precise GET per book (no search query, no result parsing)
- Minimal rate-limit impact (OL rate limits target search endpoints harder)
- High yield: ~30-60% of works have descriptions

## Tier 3: Full API Enrichment

### Source Hit Rates (all-time)

| Source | Attempts | Successes | Hit Rate | Value Add |
|--------|----------|-----------|----------|-----------|
| Open Library | 27,793 | 18,960 | 68% | Description, subjects, cover |
| Google Books | 9,853 | 966 | 9% | Categories, rating, description |
| Gutendex | 11,679 | 604 | 5% | Public domain only |
| Library of Congress | 12,093 | 0 | **0%** | Dead — never returns data |
| OCR Copyright | 11 | 6 | 54% | ISBNs from scanned pages |

**Recommendation:** Kill LoC (0% across 12K attempts). Deprioritize Gutendex (only public domain).

### Rate Limiting (AIMD)

Additive Increase / Multiplicative Decrease per source:

| Parameter | Value |
|-----------|-------|
| Base interval | 2.0s (OL), 1.5s (Google), 5.0s (Amazon) |
| Min interval | 0.5s |
| Max interval (ceiling) | 6 hours |
| Additive increase on success | 0.05s faster |
| Multiplicative decrease on failure | 2x slower |

Hard backoff from `Retry-After` headers or ban detection. State is ephemeral (resets on restart).

### Smart Routing (by ISBN prefix)

Routes French books to BnF, German to DNB, etc. Currently dormant because Tier 3 is backed off.

### Merge Strategy

When multiple sources return data:

| Field | Rule |
|-------|------|
| Title | Shortest (least cruft) |
| Description | Longest (most info) |
| Publisher | Shortest (least marketing) |
| Rating | Average across sources |
| Cover | Apple → Bookcover → OL → Google |
| Genres | Union, deduped, max 20 |

### Relevance Guard

Before applying: title word overlap ≥ 40%, ISBN match, author last-name intersection. Prevents metadata cross-contamination.

## Postprocessing

After successful enrichment:
1. Cover download (best URL found)
2. EPUB writeback (Dublin Core metadata injection)
3. File organization (Genre/Author/Title tree)
4. Series linking
5. Quality score recomputation

## Progress (2026-06-06)

| Metric | Count | % |
|--------|-------|---|
| Total books | 63,502 | 100% |
| Has ISBN | 44,680 | 70% |
| Local enriched (local_enriched=true) | 35,746 | 56% |
| Has description | 1,436 | 2% |
| Confidence scored | 5,315 | 8% |
| ISBN extract tried (no hit) | 666 | — |
| OL Works tried | 48 | — |
| No ISBN remaining | 18,822 | 30% |

## Projected Timeline (at current rates)

| Work item | Remaining | Rate | ETA |
|-----------|-----------|------|-----|
| ISBN extraction (scan files) | ~15,300 books | ~112/day | ~137 days (limited by hit rate) |
| OL Works descriptions | ~35,000 books | ~420/hour | ~3.5 days |
| Confidence scoring | ~58,000 books | ~2000/day | ~29 days |
| Title → ISBN matching | ~18,000 books | ~7,500/day | ~2.4 days |

**Critical path:** OL Works (descriptions) will finish in ~4 days. Title matching will finish in ~3 days. These feed more ISBNs into the pipeline, accelerating local enrichment.
