# Roadmap — Decisions & Code Examples

> Concrete, unambiguous code for every choice resolved after the PR #2 review
> ([response](../reviews/2026-09-30-pr2-review-response.md)). Each section shows the schema, the
> function, and (where a rule is subtle) a worked example, so implementers have no ambiguity about
> which option was chosen. Code is illustrative reference, not final — it follows the existing
> conventions (asyncpg, additive idempotent migrations, stdlib, no build step).

## Contents
- [M1 — Per-pipeline state (not one column)](#m1)
- [M2 — Reading lifecycle schema (P0 bug fix)](#m2)
- [M10 — Loop heartbeat in /health](#m10)
- [A2 — Central `eligible_books(pipeline)` gate](#a2)
- [Content types + stored LLM content + 6-month refresh](#content)
- [MT — Multi-tenant: canonical files + shared metadata + trust rule](#mt)
- [D3 — Persistent LSH bands](#d3)
- [D4 — Fused scorer, renormalized + fitted](#d4)
- [D5 — 5-class routing: exact / stack / edition / translation / probable](#d5)
- [book_files.sha256](#sha256)
- [CPU off the event loop](#cpu)
- [AI — in-app router, single ledger, local-first](#ai)
- [LibGen / Anna's Archive MD5 metadata source](#libgen)

---

<a name="m1"></a>
## M1 — Per-pipeline state (not one `processing_status` column)

**Decision:** the review is right — one column cannot express ~15 independent pipelines. Use a
per-(book, pipeline) state table with backoff, and make the JSONB-corruption class impossible.

```sql
-- migration 012 (excerpt)
CREATE TABLE IF NOT EXISTS book_pipeline_state (
    book_id      UUID    NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    pipeline     TEXT    NOT NULL,          -- 'isbn' | 'ocr' | 'title_cleanup' | 'ol_works' | 'fingerprint' | ...
    status       TEXT    NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','processing','complete','failed','skipped')),
    attempts     INT     NOT NULL DEFAULT 0,
    last_error   TEXT,
    next_retry_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (book_id, pipeline)
);
CREATE INDEX IF NOT EXISTS bps_ready_idx
    ON book_pipeline_state (pipeline, status, next_retry_at);

-- Make the fides corruption class impossible (extra_metadata degraded object -> array):
ALTER TABLE books
    ADD CONSTRAINT extra_metadata_is_object
    CHECK (jsonb_typeof(extra_metadata) = 'object') NOT VALID;   -- NOT VALID: don't fail on legacy rows
-- then, after a cleanup pass: ALTER TABLE books VALIDATE CONSTRAINT extra_metadata_is_object;
```

```python
# brainycat/pipeline_state.py
BACKOFF = [60, 300, 1800, 7200, 86400]          # seconds; index by attempts, capped
MAX_ATTEMPTS = len(BACKOFF)

async def claim(pipeline: str, limit: int) -> list[str]:
    """Rows eligible to run now: pending/failed, retry time passed, attempts left."""
    rows = await db.fetch_all(
        """UPDATE book_pipeline_state s SET status='processing', updated_at=now()
           WHERE (s.book_id, s.pipeline) IN (
             SELECT book_id, pipeline FROM book_pipeline_state
             WHERE pipeline=$1 AND status IN ('pending','failed')
               AND (next_retry_at IS NULL OR next_retry_at <= now())
               AND attempts < $2
             ORDER BY updated_at LIMIT $3
             FOR UPDATE SKIP LOCKED)
           RETURNING s.book_id""",
        pipeline, MAX_ATTEMPTS, limit)
    return [str(r["book_id"]) for r in rows]

async def done(book_id: str, pipeline: str) -> None:
    await db.execute("UPDATE book_pipeline_state SET status='complete', updated_at=now() "
                     "WHERE book_id=$1 AND pipeline=$2", UUID(book_id), pipeline)

async def fail(book_id: str, pipeline: str, err: str) -> None:
    await db.execute(
        """UPDATE book_pipeline_state
           SET status='failed', attempts=attempts+1, last_error=$3,
               next_retry_at = now() + make_interval(secs =>
                   (ARRAY[60,300,1800,7200,86400])[LEAST(attempts+1,5)]),
               updated_at=now()
           WHERE book_id=$1 AND pipeline=$2""",
        UUID(book_id), pipeline, err[:500])
```

**Contrast (rejected option):** a single `books.processing_status` — cannot say "OCR failed,
enrichment ok, fingerprint pending" and reproduces the "retry forever" bug per-book instead of
per-pipeline.

> **⚠️ ROUND-2 corrections:**
> - **Seed / claim missing rows.** `claim()` above finds nothing for a new book (no row exists yet).
>   Claim from `eligible_books LEFT JOIN book_pipeline_state` treating a missing row as `pending`
>   (`INSERT … ON CONFLICT DO NOTHING` on claim), or seed a `pending` row at ingest.
> - **Lease `processing` rows.** Add `claimed_at TIMESTAMPTZ`; on startup (and periodically) reset
>   rows stuck `processing` past a lease (`UPDATE … SET status='pending' WHERE status='processing'
>   AND claimed_at < now() - interval '1 hour'`). A crash/restart mid-run is frequent on fides.
> - **Idempotent CHECK.** Postgres has no `ADD CONSTRAINT IF NOT EXISTS`; wrap in
>   `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='extra_metadata_is_object')
>   THEN ALTER TABLE books ADD CONSTRAINT … ; END IF; END $$;`. fides has 0 non-object rows now, so
>   `VALIDATE` can run immediately there.
> - Keep the backoff schedule in **one** place (the SQL array), not duplicated in Python.

---

<a name="m2"></a>
## M2 — Reading lifecycle schema (this is a P0 BUG FIX, not a feature)

**Decision:** the routes already exist in `main` and **500 today** because the schema was never
migrated. Ship the migration using the table name the code already uses (`reading_log`, singular).

```sql
-- migration 012 (excerpt) — makes existing routes work.
-- ⚠️ ROUND-2 CORRECTION: verified against main. The routes use status value 'library'
-- (routes/reader.py:413-414), columns `minutes` + `logged_at` and a NULLable book_id with
-- MULTIPLE sessions/day (reader.py:546; book_dna.py:30) — NOT 'library_only'/minutes_read/date/
-- one-per-day. The earlier shape would have kept the routes broken (the exact mistake this fixes).
ALTER TABLE reading_progress
    ADD COLUMN IF NOT EXISTS status       TEXT DEFAULT 'library'
        CHECK (status IN ('want_to_read','reading','finished','abandoned','library')),
    ADD COLUMN IF NOT EXISTS started_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finished_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS abandoned_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS reading_log (        -- name + columns match routes/reader.py:546 & book_dna.py:30
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id    UUID REFERENCES books(id) ON DELETE CASCADE,   -- NULLable: "read 30 pages on paper"
    minutes    INT,
    pages_read INT,
    logged_at  TIMESTAMPTZ NOT NULL DEFAULT now()             -- timestamp, many sessions/day; NO unique constraint
);
CREATE INDEX IF NOT EXISTS reading_log_user_time_idx ON reading_log (user_id, logged_at);
```

This is the smallest, most urgent change and should be **migration 012 on its own** (three broken
routes fixed by one migration). No new route code — the handlers already exist in `main`.

---

<a name="m10"></a>
## M10 — Loop heartbeat in `/health` (the actually-missing piece)

**Decision:** `/health` and the rate-limit breaker already exist; the gap is **loop visibility**
(eight loops failed silently every tick for months on fides). Add a heartbeat.

```python
# brainycat/heartbeat.py — in-memory; the scheduler's _supervised wrapper writes it
_beats: dict[str, dict] = {}

def record(loop: str, ok: bool, err: str | None = None) -> None:
    b = _beats.setdefault(loop, {"consecutive_errors": 0})
    now = time.time()
    b["last_run_at"] = now
    if ok:
        b["last_ok_at"] = now
        b["consecutive_errors"] = 0
        b["last_error"] = None
    else:
        b["consecutive_errors"] += 1
        b["last_error"] = (err or "")[:300]

def health(now: float | None = None) -> dict:
    now = now or time.time()
    loops = {}
    degraded = False
    for name, b in _beats.items():
        # ⚠️ ROUND-2: per-loop threshold (3× that loop's own interval), NOT a fixed 3600s — otherwise
        # log_retention (86,400s) and isbn_extract (3,600s) report permanently stale.
        threshold = 3 * b.get("interval", 300)
        stale = b.get("last_ok_at") is None or (now - b["last_ok_at"]) > threshold
        bad = stale or b["consecutive_errors"] >= 3
        degraded = degraded or bad
        loops[name] = {**b, "healthy": not bad}
    return {"loops": loops, "degraded": degraded}
```

> **⚠️ ROUND-2:** loops that start once and loop internally (e.g. `isbn_extract`) never return from
> their tick, so the `_supervised` wrapper never records success for them. Such workers must call
> `heartbeat.record(name, ok=True, interval=…)` from **inside** their own loop body. Each loop
> registers its `interval` so `health()` can use `3× interval` as the staleness threshold.

```python
# scheduler._supervised (sketch): wrap each loop tick
async def _supervised(name, coro_factory, interval):
    while True:
        try:
            await coro_factory()
            heartbeat.record(name, ok=True)
        except Exception as e:
            heartbeat.record(name, ok=False, err=f"{type(e).__name__}: {e}")
        await asyncio.sleep(interval)
```

`/health` merges `heartbeat.health()` and returns `degraded: true` when any loop hasn't succeeded in
N intervals — which would have surfaced every silent failure on day one.

---

<a name="a2"></a>
## A2 — One central `eligible_books(pipeline)` gate (not a hand-maintained call-site list)

**Decision:** the review is right — the 13-site list is incomplete (misses `writeback_metadata`,
which writes into the file, and `contribute_back`, which submits to **Open Library**). Centralize.

```sql
-- ⚠️ ROUND-2: ONE view is not enough. Identity-rewriting pipelines must also skip 'protected'
-- (PR #1: "enrichment may ADD data, but not CHANGE identity"). And with multi-user, only the
-- canonical row (canonical_id IS NULL) is eligible, or copies drift. List columns explicitly so
-- later ALTERs to books don't silently omit them from a `SELECT b.*` view.

-- Pipelines that only ADD missing data (covers, description fill, tags):
CREATE OR REPLACE VIEW enrichable_books AS
    SELECT id, title, isbn, description, cover_path, extra_metadata, content_type, identity_status
    FROM books
    WHERE content_type = 'book'
      AND identity_status <> 'locked'
      AND canonical_id IS NULL;                 -- multi-user: canonical only

-- Pipelines that may CHANGE identity (title cleanup, ISBN extraction, sentence_match._apply_match,
-- fast_local title pass) — additionally exclude 'protected':
CREATE OR REPLACE VIEW identifiable_books AS
    SELECT id, title, isbn, content_type, identity_status
    FROM books
    WHERE content_type = 'book'
      AND identity_status = 'auto'              -- NOT protected, NOT locked
      AND canonical_id IS NULL;
```

```python
# Add-only pipeline:            SELECT ... FROM enrichable_books  WHERE ...  -- pipeline-candidate
# Identity-rewriting pipeline:  SELECT ... FROM identifiable_books WHERE ... -- pipeline-candidate
#
# writeback_metadata / contribute_back take a book_id (no candidate list) — they must do an explicit
# row check, since no view gates them:
async def guard_or_skip(book_id: str) -> bool:
    row = await db.fetch_one("SELECT content_type, identity_status FROM books WHERE id=$1", UUID(book_id))
    return row and row["content_type"] == "book" and row["identity_status"] != "locked"
```

**The enforcing test — marker-based (round-2 fix).** A blanket `FROM books` regex fails on day one
(every `WHERE id=$1` single-row fetch matches) and omits `scheduler.py`, where `_google_books_loop`,
`_cover_loop` and `_isbn_worker` candidate queries live. Require an explicit marker instead:

```python
# tests/unit/test_pipeline_gate.py
import pathlib, re
# Any candidate query (one that selects a BATCH of books to process) must be tagged
# `-- pipeline-candidate` AND select FROM a *_books view, never FROM books.
SCANNED = ["isbn.py","title_cleanup.py","sentence_match.py","deep_enrich.py","fast_local.py",
           "ol_works.py","metadata.py","format_stack.py","intelligence.py","incipit_match.py",
           "organize.py","scheduler.py"]          # scheduler.py INCLUDED (busiest)

def test_candidate_queries_use_a_view():
    offenders = []
    for m in SCANNED:
        src = pathlib.Path("brainycat", m).read_text() if (pathlib.Path("brainycat")/m).exists() \
              else pathlib.Path("brainycat/routes", m).read_text()
        for mt in re.finditer(r"--\s*pipeline-candidate", src):
            window = src[mt.start()-400:mt.start()+80]
            if "enrichable_books" not in window and "identifiable_books" not in window:
                offenders.append(f"{m}: pipeline-candidate not gated by a *_books view")
    assert not offenders, "\n".join(offenders)
```

`writeback_metadata` and `contribute_back` gate the same way: **never** write a summary's metadata
into its file or push it to Open Library. Also fold the existing `books.is_workbook` (migration 002)
into `content_type='workbook'` so there's one concept, not two.

---

<a name="content"></a>
## Content types + stored LLM content + 6-month refresh

**Decision:** store generated LLM content (speed, credits, consistency); offer refresh only after
~6 months (a newer model may be materially better).

```sql
-- migration 012 (excerpt)
ALTER TABLE books ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'book'
    CHECK (content_type IN ('book','summary','article','sample','workbook'));
CREATE INDEX IF NOT EXISTS books_content_type_idx ON books(content_type);

ALTER TABLE book_links DROP CONSTRAINT IF EXISTS book_links_link_type_check;
ALTER TABLE book_links ADD  CONSTRAINT book_links_link_type_check
    CHECK (link_type IN ('ebook_audiobook','translation','edition','summary'));
    -- ROUND-2: NO 'stack' here — stacking = one book with two book_files, not a link between books.

CREATE TABLE IF NOT EXISTS book_summaries (
    book_id UUID PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    provider TEXT, provider_ref TEXT,
    summary_kind TEXT CHECK (summary_kind IN ('key_ideas','chapter','full_text','audio')),
    source_url TEXT, is_self_generated BOOLEAN DEFAULT false,
    original_book_id UUID REFERENCES books(id) ON DELETE SET NULL,
    duration_seconds REAL, word_count INT, acquired_at TIMESTAMPTZ,
    extra JSONB DEFAULT '{}'
);

-- Stored LLM-generated content with provenance + staleness
CREATE TABLE IF NOT EXISTS ai_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                    -- 'goldmine' | 'quick_summary' | 'xray' | 'word_wise' | ...
    content TEXT NOT NULL,
    generated_with_model TEXT NOT NULL,    -- e.g. 'groq/llama-3.3-70b'
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (book_id, kind)
);
```

```python
REFRESH_AFTER = timedelta(days=182)   # ~6 months

async def get_or_note_stale(book_id: str, kind: str) -> dict:
    row = await db.fetch_one(
        "SELECT content, generated_with_model, generated_at FROM ai_content "
        "WHERE book_id=$1 AND kind=$2", UUID(book_id), kind)
    if not row:
        return {"exists": False}
    stale = (datetime.now(timezone.utc) - row["generated_at"]) > REFRESH_AFTER
    return {"exists": True, "content": row["content"],
            "model": row["generated_with_model"], "generated_at": row["generated_at"],
            "refresh_available": stale}   # UI shows "Refresh (a newer model may do better)" only if stale
```

The **goldmine** self-summary (M3 = library-vision B5) is one object: it stores its text in
`ai_content(kind='goldmine')` **and** registers a `book_summaries` row with
`is_self_generated=true, provider='self'` linked to the original.

> **⚠️ ROUND-2 corrections:**
> - **Migrate existing summaries.** Summaries already live in `books.extra_metadata->'summary'`
>   (`summaries.py:117/189`). Add a data migration into `ai_content`, or they're orphaned and there
>   are two stores.
> - **Staleness is not only time.** Also store `prompt_version` and the **source file hash**, so
>   content goes stale when the prompt changes or the underlying text changes (a stack/merge), not
>   only after 6 months.
> - **Per-user vs shared keys.** `UNIQUE(book_id, kind)` suits shared kinds (goldmine, X-Ray).
>   Per-user kinds (`ask_book`, `recap`) need `user_id` in the key once multi-user lands.
> - **Drop `'stack'` from the `book_links` CHECK** — stacking means *one book with two `book_files`*,
>   not a link between two books (contradicts §D5). Keep only if documented as a transitional marker.
> - **Folding in `is_workbook`** also needs `UPDATE books SET content_type='workbook' WHERE is_workbook`
>   and a switch in `convert.py:114–124`, which still reads the flag.

---

<a name="mt"></a>
## MT — Multi-tenant (trusted group): canonical files + shared metadata + trust rule

**Decision:** multi-user for a **trusted group the owner controls**. **No duplicate book files** — one
physical file per unique content (keyed by `book_files.sha256`), shared via `canonical_id`. Metadata
**compounds** across users. Trust rule (D): constructive/corroborated edits auto-apply; contradictory
edits go to an **admin review queue**.

```sql
-- migration 014 (excerpt)
ALTER TABLE books ADD COLUMN IF NOT EXISTS owner_id     UUID REFERENCES users(id);
ALTER TABLE books ADD COLUMN IF NOT EXISTS canonical_id UUID REFERENCES books(id);  -- NULL = is canonical
ALTER TABLE books ADD COLUMN IF NOT EXISTS visibility   TEXT DEFAULT 'shared'
    CHECK (visibility IN ('private','shared','public'));   -- trusted group: default 'shared'

-- Per-user reading state already keys on (user_id, book_id): progress, bookmarks, annotations,
-- book_notes, reading_progress.status. These stay private per user. Canonical metadata
-- (title/author/isbn/description/tags/cover) lives on the canonical row and is shared.

CREATE TABLE IF NOT EXISTS metadata_edit_queue (      -- trust rule (D): contradictory edits land here
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    field TEXT NOT NULL, old_value TEXT, new_value TEXT,
    corroborated_by TEXT,                             -- e.g. 'openlibrary:OL123W' or NULL
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Dedup on upload — store the file once:**

```python
async def ingest_dedup(user_id: str, file_path: str) -> str:
    sha = sha256_file(file_path)
    existing = await db.fetch_one(
        "SELECT b.id FROM book_files bf JOIN books b ON b.id=bf.book_id "
        "WHERE bf.sha256=$1 AND b.canonical_id IS NULL LIMIT 1", sha)
    if existing:                      # file already stored → create a virtual copy, no second file
        return await _virtual_copy(user_id, canonical_id=str(existing["id"]))
    return await _new_canonical(user_id, file_path, sha)   # first time we've seen this content
```

**Trust rule (D) — the decision the owner made, in code:**

```python
# ⚠️ ROUND-2: the earlier version was close to the INVERSE of the intended rule — it relied on an
# undefined _is_downgrade(), and when that was false an uncorroborated replacement of a trusted value
# fell through to "neutral → apply". Corrected: "neutral" is defined NARROWLY (whitespace/case only);
# ANY uncorroborated change to a trusted, non-empty value is QUEUED, not applied.

# Dynamic column names come from a module-level allowlist (repo convention, CLAUDE.md):
EDITABLE_FIELDS = {"title", "author", "isbn", "description", "publisher", "series"}

def _is_neutral(old: str, new: str) -> bool:
    return old is not None and " ".join(old.split()).lower() == " ".join(new.split()).lower()

async def submit_metadata_edit(user_id, book_id, field, new_value, is_admin) -> dict:
    if field not in EDITABLE_FIELDS:
        return {"error": "field not editable"}
    book = await db.fetch_one("SELECT title, author, isbn, description, identity_status "
                              "FROM books WHERE id=$1", UUID(book_id))
    old = book[field]
    additive   = old is None or old == ""                       # previously missing → welcome
    corrob     = await _matches_public_source(field, new_value, book)   # OL/BnF agree?
    trusted    = book["identity_status"] in ("protected", "locked") or await _was_corroborated(book_id, field)

    if is_admin or additive or corrob or _is_neutral(old, new_value):
        await _apply_canonical(book_id, field, new_value, source=f"user:{user_id}")
        return {"applied": True, "corroborated": bool(corrob), "additive": additive}

    # Any uncorroborated change to a non-empty (and especially trusted) value → admin review queue.
    await db.execute(
        "INSERT INTO metadata_edit_queue (book_id,user_id,field,old_value,new_value,corroborated_by)"
        " VALUES ($1,$2,$3,$4,$5,$6)",
        UUID(book_id), UUID(user_id), field, str(old), str(new_value), None)
    return {"applied": False, "queued_for_review": True, "trusted_target": trusted}
```

**Worked examples of rule D (corrected):**
- No ISBN; user adds a checksum-valid `9781440881565` → **additive → applied**.
- Empty description; user pastes one → **additive → applied**.
- `"Sapiens"` → `"Sapiens (my notes)"` (non-empty, uncorroborated) → **queued for admin review**.
- `"Yuval Noah Harari"` → `"Harari"` (non-empty, uncorroborated) → **queued**.
- `" Sapiens "` → `"Sapiens"` (whitespace only) → neutral → **applied**.

> **⚠️ ROUND-2 — `/books/{id}/override` ("Fix misidentified") is now dangerous under shared metadata.**
> It clears tags, categories and enrichment history. Once metadata is shared, one non-admin override
> would wipe shared data for everyone. **Route non-admin overrides through the review queue** (admin
> override still applies immediately). And the **upload race** (two concurrent uploads of the same
> file both create a canonical) is closed by the *unique* partial index on `original_sha256` +
> `ON CONFLICT` (see [`sha256`](#sha256)) — the plain index alone can't prevent it.
>
> **Data-model note:** rather than a virtual `books` row per user (duplicates every metadata column,
> forces every query through `canonical_id`), a membership table
> `user_library(user_id, book_id, added_at, visibility)` over **one** canonical `books` row is simpler
> and can't drift; per-user state already keys on `(user_id, book_id)`.

---

<a name="d3"></a>
## D3 — Persistent LSH bands (not an in-memory datasketch index)

**Decision:** persist bands in Postgres; the existing `_minhash` is a **128-function k-hash MinHash**
(positional), so banding applies directly.

```sql
CREATE TABLE IF NOT EXISTS minhash_bands (
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    band_no SMALLINT NOT NULL,
    band_hash BIGINT NOT NULL,
    PRIMARY KEY (book_id, band_no)
);
CREATE INDEX IF NOT EXISTS minhash_bands_lookup ON minhash_bands (band_no, band_hash);
```

```python
BANDS, ROWS = 32, 4          # 128 = 32*4 ; threshold t ≈ (1/32)^(1/4) ≈ 0.42 (recall-first)

def band_hashes(sig: list[int]) -> list[tuple[int,int]]:
    out = []
    for b in range(BANDS):
        chunk = tuple(sig[b*ROWS:(b+1)*ROWS])
        out.append((b, zlib.crc32(repr(chunk).encode())))   # stable across processes
    return out

# On fingerprint insert: write the 32 band rows. Candidate pairs = self-join:
CANDIDATES_SQL = """
  SELECT a.book_id AS a, b.book_id AS b
  FROM minhash_bands a JOIN minhash_bands b
    ON a.band_no=b.band_no AND a.band_hash=b.band_hash AND a.book_id < b.book_id
  GROUP BY a.book_id, b.book_id"""     # sub-quadratic; restart-safe; incremental
```

> **⚠️ ROUND-2:** books with empty/tiny fingerprints (image-only PDFs — many here) all produce the
> **same** signature, so all 32 bands collide into one bucket and the self-join emits every pair
> among them (a quadratic blow-up). Guard it:
> - **Exclude** books below a minimum k-gram count from banding (`WHERE total_chars >= MIN`); route
>   image-only PDFs to the cover-pHash path instead.
> - **Cap bucket size**: skip / log any `(band_no, band_hash)` bucket above a threshold (boilerplate-
>   heavy publisher templates cause the same blow-up on a smaller scale).

---

<a name="d4"></a>
## D4 — Fused scorer, renormalized + fitted (fixes the ISBN-less bug)

**Decision:** the original rubric couldn't reach 0.70 without ISBN (max 0.65). Renormalize over the
signals **actually present**, gate ISBN through `reject_shared`, and **fit** weights on labeled pairs.

```python
# Weighted mean over PRESENT signals — so an ISBN-less pair can still reach high confidence.
# ⚠️ ROUND-2: a bare weighted mean inflates weak pairs. With only title/author + size present
# (common, given coverage gaps), two volumes of a series (title≈0.9, size≈0.95) fuse to
# (0.20·0.9 + 0.05·0.95)/0.25 ≈ 0.91 → "probable duplicate" — the series-as-duplicates bug fixed
# on fides this week. Fixes: (1) require a MINIMUM present weight (or shrink toward a prior);
# (2) keep the numeric-token series guard from intelligence.find_duplicates; (3) prefer a fitted
# logistic model with missing-value indicators, which handles this natively.
MIN_PRESENT_WEIGHT = 0.45   # below this, not enough evidence to score — send to review, don't fuse-high

def fuse(signals: dict[str, float], weights: dict[str, float]) -> float:
    present = {k: v for k, v in signals.items() if v is not None}
    if not present:
        return 0.0
    wsum = sum(weights[k] for k in present)
    if wsum < MIN_PRESENT_WEIGHT:
        return 0.0                      # insufficient evidence — never inflate
    return sum(weights[k] * present[k] for k in present) / wsum

def looks_like_series(a, b) -> bool:
    # e.g. "... Vol. 1" vs "... Vol. 2", "Book 1" vs "Book 3": same base title, different number.
    return same_base_title(a.title, b.title) and series_number(a.title) != series_number(b.title)

# Worked example — two byte-identical texts, NO ISBN (all content signals present):
#   fuse ≈ 0.99 → flagged. Two series volumes (only title+size present, wsum=0.25 < 0.45) → 0.0 +
#   series guard → NOT flagged. (Old rubric: 0.65 missed the first; naive mean: 0.91 mis-flagged the second.)

def isbn_signal(a, b, shared_isbns: set[str]) -> float | None:
    if not a.isbn or not b.isbn:
        return None                     # missing → no signal
    if a.isbn != b.isbn:
        return 0.0                      # ⚠️ ROUND-2: two valid DIFFERENT ISBNs = evidence of a
                                        # different edition (D5 needs this), not "no signal"
    if a.isbn in shared_isbns:          # placeholder ISBN carried by many unrelated titles
        return None
    return 1.0

# ⚠️ ROUND-2: identify.reject_shared(cands, titles) is BATCH-oriented and returns a list — it is not
# a per-ISBN predicate. Precompute the shared-ISBN set once (ISBN -> >k distinct normalized titles):
def shared_isbn_set(rows, k: int = 3) -> set[str]:
    by_isbn: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["isbn"]:
            by_isbn[r["isbn"]].add(norm_title(r["title"]))
    return {isbn for isbn, titles in by_isbn.items() if len(titles) > k}

# Weights are FITTED, not guessed (charter principle 4): logistic regression on labeled pairs.
# tests/golden/fit_dedup_weights.py trains on tests/golden/dedup_pairs.tsv (true/edition/unrelated)
# and emits weights + thresholds; the scorer loads them. Fitting replaces the hand table entirely.
```

---

<a name="d5"></a>
## D5 — 5-class routing: exact / stack / edition / translation / probable

**Decision:** format ≠ edition. An EPUB+PDF of the *same* edition are **stacked** into one book, not
edition-linked. Translations (MinHash ≈ 0) use the OL `work_key` or multilingual embeddings.

```python
def classify(a, b, fused: float, signals: dict) -> str:
    # ⚠️ ROUND-2 CORRECTION: added `duplicate_copy` — the MOST COMMON real duplicate here
    # (two libgen/Anna's Archive downloads of the same EPUB, not byte-identical). The earlier
    # version let these fall through to `other_edition` and *linked* them instead of offering
    # deletion. Also: equal (non-shared) ISBN ⇒ same edition, never "other edition"; translation
    # now requires same-work evidence, not cosine alone.
    if a.original_sha256 and a.original_sha256 == b.original_sha256:
        return "exact_file_duplicate"                 # identical original bytes → delete extra copy
    same_work = (signals.get("isbn_signal") == 1.0    # equal, non-shared ISBN ⇒ SAME edition
                 or signals.get("ol_work_key_match")  # editions+translations share work_key
                 or fused >= FIT.same_work_threshold)
    same_format = (a.format == b.format)
    high_content = signals.get("minhash_jaccard", 0) >= 0.8

    if same_work and same_format and (high_content or signals.get("size_ratio", 0) >= 0.9):
        return "duplicate_copy"                       # same edition, same format, different file
                                                      # → keep best copy (fides _recommend), delete other
    if same_work and not same_format and high_content:
        return "same_edition_other_format"            # EPUB+PDF of one edition → STACK
    # translation needs SAME-WORK evidence, not cosine alone (French/English books on one topic
    # reach cosine≥0.75 without being translations):
    if (signals.get("ol_work_key_match") or signals.get("same_author_translated_title")) \
            and a.language != b.language and signals.get("minhash_jaccard", 1) < 0.2:
        return "translation"                          # → book_links('translation')
    if signals.get("isbn_signal") is None and signals.get("different_isbn"):
        return "other_edition"                        # two valid, different, non-shared ISBNs
    if same_work:
        return "other_edition"
    if fused >= FIT.probable_threshold:
        return "probable_duplicate"                   # → review queue
    return "not_duplicate"                            # → sticky dismiss
```

| Class | Evidence | Action |
|---|---|---|
| exact_file_duplicate | identical **original** `sha256` | delete extra copy |
| **duplicate_copy** (most common here) | same work + **same** `format` + high MinHash/size | keep best copy, delete the other |
| same_edition_other_format | same work + **different** `format` + MinHash ≥ 0.8 | **stack** (one book, two files) |
| other_edition | different valid non-shared ISBN / different year | `book_links('edition')` |
| translation | same-work evidence + different `language` + MinHash ≈ 0 | `book_links('translation')` |
| probable_duplicate | fused ≥ threshold | review queue |
| not_duplicate | below threshold | sticky dismiss |

> Classify on **file pairs / format sets**, not a single `a.format`, for books that already have
> several files.

---

<a name="sha256"></a>
## `book_files.sha256`

```sql
ALTER TABLE book_files ADD COLUMN IF NOT EXISTS original_sha256 TEXT;  -- bytes AS RECEIVED (immutable)
ALTER TABLE book_files ADD COLUMN IF NOT EXISTS original_md5    TEXT;  -- for LibGen/AA cross-reference
ALTER TABLE book_files ADD COLUMN IF NOT EXISTS current_sha256  TEXT;  -- of the stored file (integrity)
ALTER TABLE book_files ADD COLUMN IF NOT EXISTS anna_md5        TEXT;  -- MD5 parsed from filename, if present
CREATE INDEX IF NOT EXISTS book_files_original_sha256_idx ON book_files(original_sha256);
-- Cross-user dedup needs a UNIQUE key on canonical rows (round-2: the plain index can't prevent the race):
CREATE UNIQUE INDEX IF NOT EXISTS book_files_canonical_orig_uidx
    ON book_files(original_sha256) WHERE original_sha256 IS NOT NULL;  -- pair with ON CONFLICT on ingest
```

> **⚠️ ROUND-2 BLOCKER FIX.** BrainyCat *modifies files*: `watcher._import_file` calls `fix_epub(dst)`
> which does `os.replace(tmp_path, epub_path)` (`epub_fix.py:57`), and `writeback_metadata` later
> rewrites EPUB OPFs / PDFs. So a hash of the **stored** file won't match the LibGen/AA record (MD5 of
> the original download) or another user's upload of the same original — breaking both LibGen lookup
> and cross-user dedup. **Hash the original bytes at ingest, before `fix_epub`, and store them
> immutably** (`original_sha256`, `original_md5`). Compute `current_sha256` separately for integrity.
>
> **Free win:** 1,122 of 3,949 files on fides (28%) carry the Anna's Archive MD5 in the filename
> (`… -- <32 hex> -- Anna's Archive.epub`). Parse it into `anna_md5` at ingest — the
> filename-standardizing rename drops it, but `filename_history` retains the old names for backfill.

```python
def ingest(user_id, incoming_path):
    orig_sha = sha256_file(incoming_path)                 # BEFORE any modification
    orig_md5 = md5_file(incoming_path)                    # for LibGen/AA
    anna_md5 = re.search(r"--\s*([0-9a-f]{32})\s*--\s*Anna", os.path.basename(incoming_path))
    dst = move_into_library(incoming_path)
    fix_epub(dst)                                         # may rewrite dst in place → changes its hash
    # store orig_sha / orig_md5 / anna_md5 immutably; current_sha256 computed after fixes
```

Exact-duplicate detection becomes `GROUP BY original_sha256`; it is also the key for cross-user dedup
([MT](#mt)) and the LibGen/AA source ([below](#libgen)).

---

<a name="cpu"></a>
## CPU off the single event loop (prerequisite for any dedup time budget)

**Decision:** accepted. `intelligence.find_duplicates` took 50–60 s at 3.9K books with the API
unresponsive. Move CPU-bound work off the loop.

```python
# Before (blocks every request for the whole run):
result = fingerprint_and_score(book)          # pure-Python, seconds

# After:
result = await asyncio.to_thread(fingerprint_and_score, book)   # yields the loop
# or route batch dedup / fitz page rendering to a dedicated worker process.
```

---

<a name="ai"></a>
## AI — in-app router (owner decision 2), single ledger, local-first

**Decision:** bring routing **in-app** ("Intello in spirit"). Consolidate call sites first (AI0), keep
**one cost ledger in Postgres** with per-intent budgets (so budget control isn't lost), and be
**local-first** — cloud providers opt-in per intent, never full book text to cloud unless enabled.

```python
# AI0 — one interface all features call (replaces companion._llm, translators/llm.py, worddumb, /goldmine)
class Intent(str, Enum):
    OCR_CLEANUP = "ocr_cleanup"; GENRE = "genre_classify"; BOOK_DESC = "book_description"
    CHAPTER_SUMMARY = "chapter_summary"; GOLDMINE = "goldmine"; TRANSLATE = "translate"
    WORD_WISE = "word_wise"; XRAY = "xray"; ASK_BOOK = "ask_book"; RECAP = "recap"; IDENTIFY = "identify"

# Per-intent defaults: quality tier, cost ceiling, latency, and whether cloud/full-text is allowed.
INTENT_POLICY = {
    Intent.OCR_CLEANUP:   dict(quality="low",  max_cost=0.001, latency="batch",       allow_cloud=True,  allow_full_text=False),
    Intent.GOLDMINE:      dict(quality="high", max_cost=0.05,  latency="batch",       allow_cloud=False, allow_full_text=True),   # book text → local only by default
    Intent.ASK_BOOK:      dict(quality="high", max_cost=0.02,  latency="interactive", allow_cloud=True,  allow_full_text=False),
    # ...
}

async def complete(intent: Intent, prompt: str, *, book_text: str | None = None) -> "LLMResponse":
    policy = INTENT_POLICY[intent]
    if book_text and not policy["allow_full_text"]:
        raise ValueError(f"{intent} must not send full book text unless enabled")
    decision = route(intent, prompt, policy)          # ports Intello's scoring/AIMD/rate-limits IN-APP
    await budgets.check(intent, decision.est_cost)    # single Postgres ledger, per-intent budget
    resp = await execute(decision, prompt)            # local-first (Ollama) unless policy.allow_cloud
    await budgets.record(intent, decision.provider, resp.cost)
    return resp
```

```sql
-- single ledger in BrainyCat's Postgres (not a second SQLite; preserves one budget view)
CREATE TABLE IF NOT EXISTS ai_cost_ledger (
    id BIGSERIAL PRIMARY KEY, intent TEXT, provider TEXT, model TEXT,
    input_tokens INT, output_tokens INT, cost_usd NUMERIC(12,6),
    book_id UUID, user_id UUID, ts TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS ai_budgets (
    scope TEXT PRIMARY KEY,            -- 'global' | intent name
    daily_usd NUMERIC(12,4), monthly_usd NUMERIC(12,4));
```

The provider catalog + scoring is ported from Intello's `router.py`/`models.py` (which the review
confirmed is well-built); the difference is the caller passes `Intent` (real business context)
instead of relying on keyword `classify_task`.

> **⚠️ ROUND-2 notes:**
> - **Define "full text" precisely.** `ASK_BOOK` needs RAG *excerpts*, so `allow_full_text=False`
>   must mean "at most N tokens of excerpts per call, passed as a **structured argument**" — never
>   book text smuggled inside `prompt` (which would bypass the guard). Specify N.
> - **Measure local goldmine throughput first.** Whole-book summarization of ~3,900 books on CPU with
>   a capable local model may take **weeks**. Allow an explicit per-book **cloud opt-in** (or batch
>   it) rather than discovering this after building.
> - **Ledger scope is BrainyCat-only.** It preserves BrainyCat's budgets, but other projects still
>   spend through Intello — a *global* cap would need one ledger to report to another. Known limit,
>   the owner's call, noted so it isn't a surprise.

---

<a name="libgen"></a>
## LibGen / Anna's Archive MD5 metadata source (owner decision A: yes; metadata only)

**Decision:** yes — **metadata only**, keyed by file MD5. Most incoming filenames end in `libgen.li`
/ `Anna's Archive`; an exact hash lookup identifies a book with no fuzzy matching.

```python
# One entry in the offline LocalSource registry (C2). Metadata only — no content, no file transfer.
async def identify_by_md5(book_file_row) -> dict | None:
    # ⚠️ ROUND-2: use the ORIGINAL-download MD5 (parsed from an Anna's Archive filename, or the
    # original_md5 captured at ingest BEFORE fix_epub) — NOT a hash of the modified stored file,
    # which won't match the LibGen/AA index.
    md5 = book_file_row["anna_md5"] or book_file_row["original_md5"]
    if not md5:
        return None
    row = local_libgen_db.execute(
        "SELECT title, author, isbn, year, publisher, language "
        "FROM md5_meta WHERE md5=? LIMIT 1", (md5,)).fetchone()
    return dict(row) if row else None
# Registered with a disk_budget (measured: OL editions dump 12.6 GB → 14 GB index), enabled
# per-instance, off by default; local-first in metadata.enrich_book before any network call.
```

**Legal/ethical note (owner-approved; repo is public — describe carefully):** this is
**hash-keyed bibliographic metadata**, off by default, enabled per instance. No book content is
downloaded or served; the dumps are used only to identify files the owner already possesses.
