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

---

<a name="m2"></a>
## M2 — Reading lifecycle schema (this is a P0 BUG FIX, not a feature)

**Decision:** the routes already exist in `main` and **500 today** because the schema was never
migrated. Ship the migration using the table name the code already uses (`reading_log`, singular).

```sql
-- migration 013 (excerpt) — makes existing routes work
ALTER TABLE reading_progress
    ADD COLUMN IF NOT EXISTS status       TEXT DEFAULT 'library_only'
        CHECK (status IN ('want_to_read','reading','finished','abandoned','library_only')),
    ADD COLUMN IF NOT EXISTS started_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finished_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS abandoned_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS reading_log (        -- name matches routes/reader.py + experimental/book_dna.py
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id      UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    date         DATE NOT NULL,
    pages_read   INT,
    minutes_read INT,
    UNIQUE (user_id, book_id, date)
);
```

No new route code — the `PUT /books/{id}/status`, `/reading/streak`, `POST /reading/log` handlers in
`routes/reader.py` start working once these exist. UI wiring is the only remaining *feature* work.

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
        stale = b.get("last_ok_at") is None or (now - b["last_ok_at"]) > 3600
        bad = stale or b["consecutive_errors"] >= 3
        degraded = degraded or bad
        loops[name] = {**b, "healthy": not bad}
    return {"loops": loops, "degraded": degraded}
```

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
-- A book is eligible for automated pipelines only when it's a real 'book',
-- not locked, and not a summary/workbook/article/sample.
CREATE OR REPLACE VIEW eligible_books AS
    SELECT b.*
    FROM books b
    WHERE b.content_type = 'book'
      AND b.identity_status <> 'locked';
```

```python
# Every pipeline candidate query selects FROM eligible_books, never FROM books directly.
# Example — the ISBN worker:
rows = await db.fetch_all(
    "SELECT id, isbn FROM eligible_books WHERE isbn IS NULL LIMIT $1", batch)
```

**The enforcing test (fails when a new pipeline forgets the gate):**

```python
# tests/unit/test_pipeline_gate.py
import pathlib, re
PIPELINE_MODULES = ["isbn.py","title_cleanup.py","sentence_match.py","deep_enrich.py",
    "fast_local.py","ol_works.py","metadata.py","format_stack.py","writeback.py",
    "contribute.py","incipit_match.py","organize.py","intelligence.py"]

def test_pipelines_select_from_eligible_books():
    offenders = []
    for m in PIPELINE_MODULES:
        src = pathlib.Path("brainycat", m).read_text()
        # any 'FROM books' that isn't 'FROM eligible_books' in an automated candidate query
        for match in re.finditer(r"FROM\s+books\b", src):
            offenders.append(f"{m}: {src[match.start()-40:match.start()+20]!r}")
    assert not offenders, "pipeline selects FROM books instead of eligible_books:\n" + "\n".join(offenders)
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
    CHECK (link_type IN ('ebook_audiobook','translation','edition','summary','stack'));

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
async def submit_metadata_edit(user_id, book_id, field, new_value, is_admin) -> dict:
    book = await db.fetch_one("SELECT title, isbn, description FROM books WHERE id=$1", UUID(book_id))
    old = book[field]

    corrob = await _matches_public_source(field, new_value, book)   # OL/BnF/etc. agree?
    additive = (old is None or old == "")                            # was previously missing?
    contradicts = (old not in (None, "")) and not corrob and _is_downgrade(field, old, new_value)

    if is_admin or additive or corrob:
        # Constructive/corroborated (or admin) → apply to the shared canonical record now.
        await _apply_canonical(book_id, field, new_value, source=f"user:{user_id}")
        return {"applied": True, "corroborated": bool(corrob)}
    if contradicts:
        # Goes against trusted data → queue for admin review, do NOT touch the shared record.
        await db.execute(
            "INSERT INTO metadata_edit_queue (book_id,user_id,field,old_value,new_value,corroborated_by)"
            " VALUES ($1,$2,$3,$4,$5,$6)",
            UUID(book_id), UUID(user_id), field, str(old), str(new_value), corrob)
        return {"applied": False, "queued_for_review": True}
    # Neutral change (e.g. reformatting) → apply.
    await _apply_canonical(book_id, field, new_value, source=f"user:{user_id}")
    return {"applied": True}
```

**Worked examples of rule D:**
- Book has no ISBN; user adds `9781440881565` that checksums valid → **additive → applied**.
- Description empty; user pastes a description → **additive → applied**.
- Title is `"Sapiens"` (matches Open Library); user changes it to `"Sapiens (my notes)"` →
  contradicts trusted data, not corroborated → **queued for admin review**.
- Author `"Yuval Noah Harari"` (corroborated); user changes to `"Harari"` → downgrade, not
  corroborated → **queued**. Admin can approve if intended.

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

---

<a name="d4"></a>
## D4 — Fused scorer, renormalized + fitted (fixes the ISBN-less bug)

**Decision:** the original rubric couldn't reach 0.70 without ISBN (max 0.65). Renormalize over the
signals **actually present**, gate ISBN through `reject_shared`, and **fit** weights on labeled pairs.

```python
# Weighted mean over PRESENT signals — so an ISBN-less pair can still reach high confidence.
def fuse(signals: dict[str, float], weights: dict[str, float]) -> float:
    present = {k: v for k, v in signals.items() if v is not None}
    if not present:
        return 0.0
    wsum = sum(weights[k] for k in present)
    return sum(weights[k] * present[k] for k in present) / wsum   # normalized to [0,1]

# Worked example — two byte-identical texts, NO ISBN on either:
#   signals = {minhash_jaccard: 1.0, title_author_sim: 1.0, cover_phash: 0.9, skeleton: 1.0, size_ratio: 1.0}
#   (isbn_equal absent)  → fuse = weighted mean of present ≈ 0.99  → flagged. (Old rubric: 0.65, missed.)

def isbn_signal(a, b) -> float | None:
    if not a.isbn or not b.isbn or a.isbn != b.isbn:
        return None
    if reject_shared(a.isbn):          # baseline.md: one ISBN shared by 29 unrelated files
        return None                    # weak/placeholder ISBN → don't let it count
    return 1.0

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
    if a.sha256 and a.sha256 == b.sha256:
        return "exact_file_duplicate"                 # → delete the extra copy
    same_work = (signals.get("isbn_signal") == 1.0
                 or signals.get("ol_work_key_match")           # editions+translations share work_key
                 or fused >= FIT.stack_threshold)
    if same_work and a.format != b.format and signals.get("minhash_jaccard", 0) >= 0.8:
        return "same_edition_other_format"            # → STACK via format_stack.verify_and_stack()
    if signals.get("minhash_jaccard", 0) < 0.2 and signals.get("multilingual_cos", 0) >= 0.75:
        return "translation"                          # → book_links('translation')
    if same_work:
        return "other_edition"                        # → book_links('edition')
    if fused >= FIT.probable_threshold:
        return "probable_duplicate"                   # → review queue
    return "not_duplicate"                            # → sticky dismiss
```

| Class | Evidence | Action |
|---|---|---|
| exact_file_duplicate | identical `sha256` | delete extra copy |
| same_edition_other_format | same work + different `format` + MinHash ≥ 0.8 | **stack** (one book, two files) |
| other_edition | same work, different ISBN/year | `book_links('edition')` |
| translation | MinHash ≈ 0 + multilingual cosine ≥ 0.75 (or shared `work_key`) | `book_links('translation')` |
| probable_duplicate | fused ≥ threshold | review queue |
| not_duplicate | below threshold | sticky dismiss |

---

<a name="sha256"></a>
## `book_files.sha256`

```sql
ALTER TABLE book_files ADD COLUMN IF NOT EXISTS sha256 TEXT;
CREATE INDEX IF NOT EXISTS book_files_sha256_idx ON book_files(sha256);
```
Computed at ingest, backfilled once. Exact-duplicate detection becomes
`SELECT sha256 FROM book_files GROUP BY sha256 HAVING count(*)>1` instead of re-MD5ing on every run,
and it is the key for both cross-user dedup ([MT](#mt)) and the LibGen/AA source ([below](#libgen)).

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

---

<a name="libgen"></a>
## LibGen / Anna's Archive MD5 metadata source (owner decision A: yes; metadata only)

**Decision:** yes — **metadata only**, keyed by file MD5. Most incoming filenames end in `libgen.li`
/ `Anna's Archive`; an exact hash lookup identifies a book with no fuzzy matching.

```python
# One entry in the offline LocalSource registry (C2). Metadata only — no content, no file transfer.
async def identify_by_md5(file_path: str) -> dict | None:
    md5 = md5_file(file_path)                          # LibGen/AA index is MD5-keyed (not sha256)
    row = local_libgen_db.execute(
        "SELECT title, author, isbn, year, publisher, language "
        "FROM md5_meta WHERE md5=? LIMIT 1", (md5,)).fetchone()
    return dict(row) if row else None
# Registered with a disk_budget (the OL editions dump alone is 12.6 GB → 14 GB index — measured),
# enabled per-source, local-first in metadata.enrich_book before any network call.
```

**Legal/ethical note (owner-approved):** metadata only (bibliographic facts), no book content is
downloaded or served; the dumps are used purely to identify files the owner already possesses.
