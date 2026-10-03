# Bugs & Technical Debt

## Fixed (2026-06-05)

### ~~Confidence loop bug~~ — FIXED

`'bool' object has no attribute 'get'` crashed every 60s. 13,209 books had `extra_metadata.local_title_tried = true` (boolean instead of dict). Fixed by adding `isinstance(local_title, dict)` guard in Signal 6 of `confidence.py`.

### ~~Missing modules crashing scheduler~~ — FIXED

`ocr_copyright`, `cover_phash`, `incipit_match` modules didn't exist, causing import errors every tick. Created stub modules that return empty results.

### ~~ISBN extraction never ran~~ — FIXED

`isbn.batch_extract_isbns()` existed but was never called from the scheduler. Added `isbn_extract` loop (15s interval, 5 books/batch). Already extracted 112 ISBNs overnight.

### ~~OL Works descriptions not fetched~~ — FIXED

34,778 books had local enrichment but no description. Created `ol_works.py` that uses `work_key` from local SQLite for surgical `/works/{key}.json` GET requests. Added `ol_works` loop (3s interval).

### ~~Event loop starvation~~ — SOLVED

`isbn_extract` loop's sync file I/O (zipfile, fitz) blocked all other coroutines. Solved by moving to a dedicated daemon thread with its own psycopg2 connection. The thread processes books at natural I/O speed — no asyncio involvement at all.

---

## Active

### 1. Enrichment loop timeouts — external APIs banned

**Symptom:** Every 10s tick, all 6 locked books emit `enrichment_timeout`.

**Impact:** Zero external API enrichment. ~18K books without ISBN can't progress via API.

**Root cause:** Open Library connection resets, Google 429s. AIMD rate limiter backs off automatically (up to 6 hours). Will retry when bans lift.

**Mitigation:** The new `ol_works` loop bypasses the full enrichment pipeline by using targeted GET requests with known work_keys. This is the productive path.

---

### 2. Statement timeouts on startup burst

**Symptom:** `canceling statement due to statement timeout` for multiple loops simultaneously, 30-45s after restart.

**Impact:** First tick of several loops fails. Self-recovers on subsequent ticks.

**Root cause:** All 16 loops fire within a 30s window after startup. Under combined load, some queries exceed the 30s statement_timeout.

**Mitigation:** Indexes added (idx_books_no_isbn, idx_bookfiles_format, idx_books_ol_works). Startup stagger (15-45s random per loop) helps but doesn't eliminate the burst.

---

### 3. JSONB type inconsistency (local_title_tried)

**Symptom:** 13,209 books have `local_title_tried = true` (boolean), others have it as a dict `{isbn_from, confidence, ol_key}`.

**Impact:** Code must always guard with `isinstance(val, dict)` before calling `.get()`. Confidence loop was the main victim (now fixed).

**Fix (not yet applied):**
```sql
-- Nuclear option: clear the bad booleans
UPDATE books SET extra_metadata = extra_metadata - 'local_title_tried'
WHERE jsonb_typeof(extra_metadata->'local_title_tried') = 'boolean';
-- Then re-run fast_local_title to re-evaluate these books properly
```

---

### 4. LoC source — 0% hit rate, 12,093 wasted calls

**Impact:** Wasted API budget and log noise.

**Status:** Still active in the enrichment sources list. Deprioritized since the enrichment loop is backed off anyway. Should be removed from the source dispatch.

---

### 5. tools.ecb.pm/brainycat/ — broken reverse proxy

**Symptom:** 502 Bad Gateway from outside LAN.

**Cause:** Caddy on ecb.pm proxies to Docker DNS `brainycat:8000` — no such container on ecb.pm (it runs on sake).

**Fix:** Point Caddy to sake's LAN IP:8000, or set up a tunnel.

---

## Low Priority

### 6. ebooklib FutureWarning

```
FutureWarning: This search incorrectly ignores the root element
```
Harmless but noisy. Suppress with `warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")`.

### 7. text_profiler intermittent statement_timeout

Sometimes hits 30s timeout on its candidate query. Self-recovers. Would benefit from a partial index on `book_fingerprints.book_id IS NULL`.

### 8. Intello integration disabled

`BRAINYCAT_INTELLO_URL` is intentionally empty to avoid 15s timeout cascades. OCR, TTS, and LLM features are offline. Re-enable when Intello connectivity is confirmed stable.
