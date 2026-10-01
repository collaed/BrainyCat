# Review — PR #2 "Roadmap: library vision + dedup overhaul"

> Reviewer notes, 2026-09-30. Scope: all 9 files in the PR (`roadmap/master-improvement-plan.md`,
> `roadmap/library-vision.md`, `roadmap/dedup-overhaul.md`, `roadmap/ai-in-app.md`, `backlog.md`,
> `onboarding.md`, and the `roadmap.md` / `user-journeys.md` / `selfhosted-post.md` diffs), plus the
> charter the PR restates (the six principles in `docs/roadmap.md`).
>
> Method: every PR file was read in full; every checkable claim was verified against `main`
> (`git show main:<path>`) and, where behaviour matters, against the running fides instance
> (Postgres schema, live timings, real library data). Line references below are to `main` at
> `0929e80` unless stated otherwise.
>
> This review does not edit the PR's documents. It assesses each point for **feasibility**,
> **opportunity**, and **actual value**, critiques the plans, and proposes improvements and a
> re-sequencing.

---

## 1. Verdict

The PR is a strong piece of planning: requirement-tagged, test-driven, incremental, explicit about
reversibility and no-Intello degradation, and faithful to the charter in spirit. The diagnosis of
`brainycat/fingerprints.py` is accurate line by line (and in one case understates the problem). The
owned-summaries idea is original and well reasoned. The backlog gives the program a single place to
live, which it did not have before.

It should not be executed as written, for four reasons:

1. **It is built on code that is not in `main`.** The PR itself says `offline_bootstrap.py`,
   `ol_local.py`, `cover_phash.py`, `text_profiler.py`, the embeddings pipeline and `devdocs/` live
   only in the author's local tree. Independently, the fides working tree carries ~92 uncommitted
   files from the 2026-09-28/30 session, several of which overlap the roadmap directly (a second,
   independent `ol_local.py` with a built 14 GB index; dedup recommendation UI; scheduler changes).
   Two unmerged trees plus a roadmap is a guaranteed merge conflict and duplicated work — it has
   already happened once (`ol_local`).
2. **About ten "recovered ideas" already exist in `main`** as backend routes or experimental
   modules — some working, some broken because their schema was never migrated, almost none wired
   to the UI. Treating them as greenfield double-counts effort and invites a third implementation.
3. **Several technical errors would cause real failures if implemented as written** — most
   importantly, the dedup fusion rubric cannot flag any pair that lacks an ISBN, format stacking is
   conflated with edition linking, a single `processing_status` column cannot represent ~15
   independent pipelines, and the summary-gating list misses the two call sites that write outside
   the system (`writeback_metadata` into the file itself, `contribute_back` into Open Library).
4. **It misses the cross-cutting failure modes actually observed in production:** CPU-bound work
   blocking the single event loop, loops that fail silently every tick for months, schema that code
   depends on but no migration creates, and seven-plus overlapping dedup paths.

None of these invalidate the direction. They change the order (a Phase 0 to land and reconcile code,
a Phase 1 of correctness/observability) and reshape a handful of tasks. Details follow.

---

## 2. What already exists in `main` (the "recovered ideas" are not greenfield)

Each row was verified in `main`. "UI" means a caller exists in `static/*.html`.

| PR item | What exists in `main` | UI | Runtime status | Real remaining work |
|---|---|---|---|---|
| M2 book status enum | `PUT /books/{id}/status` with `want_to_read/reading/finished/abandoned/library` (`routes/reader.py:425–445`) | no | **Broken** — writes `reading_progress.status/started_at/finished_at`, but `reading_progress` has none of these columns (only `is_finished`); no migration adds them | Ship the migration the PR describes (it is correct) — as a **P0 bug fix**, not a P1 feature — then wire UI |
| M2 streaks | `GET /reading/streak` (`reader.py:507`), derived from `reading_progress.updated_at` | no | Works | UI only |
| M2 reading logs | `POST /reading/log` inserts into `reading_log` (`reader.py:561`); the reading-stats query (`reader.py:574–584`) and `experimental/book_dna.py` read it | no | **Broken** — table `reading_log` does not exist (`to_regclass` is null on fides) and no migration creates it | Migration for `reading_log` (the PR calls it `reading_logs` — use the name the code already uses) |
| M2 reading-time estimate | `books.estimated_reading_minutes` (migration 007), exposed in OPDS (`opds.py:118`) | partial | Works where populated | Populate for all books; show in UI |
| M2 "Continue reading" shelf | `static/index.html:133` (`#continue-reading`) | yes | Works | None — drop from the plan |
| M3 summaries / goldmine | `GET/POST /books/{id}/summary`, `POST /books/{id}/goldmine` (`routes/books.py:833–850`) | no | Needs Intello | Unify with library-vision B5 (as the PR proposes) — but start from these routes |
| M4 LoC removal | Already removed from enrichment in commit `9df101f` (2026-06-09, "0% hit rate over 12K calls") | — | Done | Delete dead `sources/loc.py` and the LoC branches in `sources/regional.py` |
| M5 Word Wise / X-Ray | `POST /books/{id}/word-wise`, `/xray` (`routes/books.py:713–727`) + `worddumb.py` | no | Needs Intello | Reader overlay (UI) only |
| M6 "you already own this" | `GET /check-owned` with ISBN/title/fuzzy match (`routes/catalog.py:340`) | no | Works | Call it from `catalog.html` results |
| M6 page-level FTS | `GET /search/fulltext` (`routes/books.py:1557`), `search_index.py`, `content_index` | no | Behind `enable_fts` | Snippets (`ts_headline`) + UI |
| M7 bulk editor | `POST /bulk/tag`, `POST /books/batch/tag` | no | Works (tags only) | Extend to author/publisher/status + UI |
| M9 Book DNA / wrap-up | `experimental/book_dna.py`, `share_cards.py`, `reading_heatmap.py` | no | Depends on the broken `reading_log` / `finished_at` | Fix M2 schema first |
| M10 health | `GET /health` checks DB, Intello, disk (`routes/health.py`) | — | Works | Add loop heartbeats (see §4.9) |
| M10 circuit breaker | `rate_limit.py`: failure backoff with 300 s cooldown per domain, `is_backed_off()` used by callers | — | Works for sources and Intello lookups | Surface state in `/health`; the breaker itself largely exists |
| D3 LSH | `experimental/lsh_dedup.py` (datasketch `MinHashLSH`, in-memory, flag `exp_lsh_dedup`) | admin | Experimental | Decide: adopt or replace (see §4.6) |
| Sentence identification | `sentence_match.py`, wired into `metadata.enrich_book` (`metadata.py:186`) — Google Books `volumes?q="…"` full-text search, accepts exactly one hit | — | Works (rate-limited) | Measure hit rate; improve sentence picker (§8) |

**Recommendation.** Replace the "Recovered ideas" framing with this kind of gap table in the master
plan, and re-grade the backlog accordingly: M2's schema gap is a **P0 bug** (routes 500 today),
M4's LoC part is done, M5/M6/M7 are mostly **UI wiring** (small), not design work.

**Pattern worth naming.** The M2 finding is the third instance of the same failure class on this
codebase: code that reads/writes schema that no migration ever created (`books.original_filename` /
`book_originals` — see `docs/known-issues.md`; `reading_log` and the `reading_progress` status
columns here; `extra_metadata` assumed to always be a JSON object). A one-off **schema-vs-code
audit** (collect every column/table referenced in SQL strings, diff against `information_schema`)
belongs in P0 and would catch the rest in one pass.

---

## 3. Factual corrections

1. **`devdocs/` is cited as a source but does not exist in `main`.** Fine for the author's context;
   for reviewers it should be called out like the unmerged modules are.
2. **"63K books"** appears nowhere in the repository. fides has 3,899 books; the published
   `selfhosted-post.md` says 1,528; the identification baseline measured 1,956 files. DR1's
   performance target should state the actual scale and a measured baseline (see §4.7 for one).
3. **DR7 describes `_minhash` as a bottom-k sketch; it is not.** `fingerprints.py:169–199`
   truncates the input set to its 50,000 smallest values (`_MINHASH_MAX_INPUT`), then computes a
   classic **128-function k-hash MinHash** (`min(hash((i, v)) …)` for `i in range(128)`). That is
   good news for D3: the signature is positional, so LSH banding applies to it directly. One caveat
   the docstring glosses over: truncating each book's set *independently* biases the Jaccard
   estimate downward when the two sets differ greatly in size (typical for PDF vs EPUB of the same
   text). A true bottom-k over the union, or a higher cap, removes the bias.
4. **Defect 1 is worse than described.** `find_duplicates_by_content` has no cursor: the book list is
   re-sorted by title on every call and `checked` counts outer-loop rows, so every run re-compares
   the *same* first `batch_size` books against everything, and any pair where both books sort after
   position `batch_size` is **never** compared, on any run. (Disclosure: the fides working tree now
   calls this every 20 s with `batch_size=20` — added in the 2026-09-30 session to revive the loop —
   which re-scans the same 20 books forever. Listed under Phase 0.)
5. **M12 is a runtime bug, not only a test-collection problem.** `routes/admin.py:119–131` imports
   `detect_calibre_library` from `calibre_import.py`, which defines only `import_calibre_library`.
   The Calibre-import admin endpoints raise `ImportError` when called.
6. **onboarding.md documents unmerged code as present:** `brainycat/confidence.py` (not in `main` —
   it is one of the modules the scheduler imports and fails on), `BRAINYCAT_OFFLINE_LOOKUP` (not in
   `config.py`), "~16 supervised loops" (the count depends on which tree), and a `docker cp`
   deployment (fides builds with `docker compose up -d --build`). Mark these "pending merge" or land
   the code first.
7. **Translation backends.** Not in the PR, but relevant to `ai-in-app.md`:
   `translation.list_backends()` advertises five backends; `_get_backend()` implements two (`argos`,
   `llm`). DeepL, Google and Ollama are offered in the UI and silently return `None`.
8. **Sentence search.** `sentence_match.py` already implements "extract a notable sentence and search
   it" using the Google Books full-text API — the correct mechanism. (Disclosure: a pilot run in the
   2026-09-30 session used the generic `WebSearch` tool instead, which does not honour exact-phrase
   matching; its 0/11 result is retracted as non-representative.)

---

## 4. Technical assessment and improvements, plan by plan

### 4.1–4.7 `dedup-overhaul.md`

**Diagnosis: correct.** Verified in `fingerprints.py:336–385`: the capped loop (defect 1, see §3.4),
the discarded size ratio on line 353 (defect 2), the bare `sim > 0.3` (defect 3), exact skeleton
`==` with an 80% floor (defect 4), and no signal fusion (defect 5). Coverage gaps (defect 6) are
real on fides as well. **Value: high** — dedup is the most-requested cleanup action in practice, and
the current content path is effectively inert.

**4.1 The fusion rubric cannot flag ISBN-less pairs.** Weights are a linear sum with
`isbn_equal = 0.35`. Without ISBN the maximum reachable score is
0.25 + 0.20 + 0.10 + 0.05 + 0.05 = **0.65**, below the 0.70 "probable" threshold. Two byte-identical
texts with no ISBN on either side can never be flagged — and ISBN-less books are exactly the ones
this library struggles with. Separately, ISBN equality is a *weak* signal here:
`docs/specs/book-identification/baseline.md` found one ISBN carried by 29 unrelated files. Improvements:
- Renormalize over the signals actually present (weighted mean of available signals), or better,
  combine as log-likelihood ratios / a logistic model **fitted** on the D4 labeled pairs. Fitting
  gives the weights instead of guessing them, and satisfies charter principle 4 (evaluate before
  committing).
- Pass ISBN equality through `identify.reject_shared()` before it counts.
- Treat an exact file hash as a hard override (it already is in the class table — keep it).

**4.2 Format is not edition.** The "same-work-different-edition" class is defined as "high
content/ISBN match but differing format/language/size" and routed to `book_links('edition')`. An
EPUB and a PDF of the *same* edition are the same book: charter principle 2 ("EPUB + PDF + audiobook
= one book") and the existing `format_stack.verify_and_stack()` both say they should be **stacked**
into one `books` row with two `book_files`, not linked as two works. Proposed classes:

| Class | Typical evidence | Action |
|---|---|---|
| exact file duplicate | identical file hash | delete the extra copy |
| same edition, other format | high MinHash / same ISBN, different `format` | **stack** (`format_stack`) |
| other edition, same language | same work, different ISBN/year/pagination | `link 'edition'` |
| translation | same work, different language — MinHash ≈ 0 | `link 'translation'` |
| probable duplicate / unrelated | as in the PR | review / discard (sticky) |

Translations are invisible to MinHash (different words). Usable signals: the Open Library **work
key** (the fides `ol_local` index already stores `work_key` per ISBN — editions and translations of
one work share it), multilingual embeddings (§4.15), or comparing strict-prompt chapter summaries.

**4.3 Tell the human what to keep.** DR6 lists actions but not the decision support that makes a
review queue fast: which copy to keep (a text-bearing EPUB or text-layer PDF over an image-only
scan; more formats; the more complete copy), how much disk is reclaimed, and sort orders
(most-likely first, least-likely first, most space first). This is already built in the fides tree
(`fingerprints._side_profile/_recommend`, `static/intel-content-dupes.html`: "no text layer" flag
from characters-per-KB, keep recommendation, reclaimable bytes, one-click delete of the loser) —
fold it into D6 instead of rebuilding.

**4.4 Consolidate, do not add an eighth path.** Duplicate logic currently lives in:
`fingerprints.find_duplicates_by_content`, `fingerprints.find_exact_duplicates`,
`intelligence.find_duplicates` (metadata-based, O(n²)), `format_stack`, `dedup_engine`,
`smart_merge`, `edition_diff`, `experimental/lsh_dedup`, `experimental/text_profile_sig`,
`experimental/dupe_pages`, and two separate review UIs. The overhaul should name which of these it
replaces, which become signals in the fused scorer (e.g. TextProfileSignature is a cheap,
reformat-robust near-duplicate signal), and retire the rest — otherwise it becomes one more.

**4.5 Store a file hash.** `book_files` has no content hash; `find_exact_duplicates` re-reads and
MD5s same-size files on every run. Add `book_files.sha256` (computed at ingest, backfilled once):
exact duplicates become a SQL `GROUP BY`, integrity checks become possible, and hash-keyed metadata
sources (§4.14) become usable.

**4.6 Make LSH persistent and incremental.** D3 leaves `b` and `r` open and does not say where band
hashes live. The existing `experimental/lsh_dedup.py` keeps a datasketch index in memory (lost on
restart, rebuilt from scratch). Recommended: a `minhash_bands(book_id, band_no, band_hash)` table
with an index on `(band_no, band_hash)`, written when a fingerprint is stored; candidates are a
self-join grouped by pair. Incremental, restart-safe, idiomatic for the asyncpg stack. For 128
rows: 32 bands × 4 rows gives a candidate threshold of ≈ (1/32)^(1/4) ≈ 0.42 (recall-first — the
fused scorer supplies precision); 16 × 8 gives ≈ 0.71.

**4.7 CPU-bound work must leave the event loop.** The app is one asyncio process. On fides,
`intelligence.find_duplicates` (pure-Python O(n²) over 3.9K books) took 50–60 s during which the API
did not answer `/health`. Page rendering (`fitz`) in request handlers and fingerprint computation
have the same shape. Any DR1 time budget is only meaningful once scoring runs in
`asyncio.to_thread`, a process pool, or a separate worker. Make it an explicit prerequisite.

### 4.8–4.10 `master-improvement-plan.md`

**4.8 M1 — one column is the wrong shape.** A book has roughly fifteen independent pipelines (ISBN
extraction, OCR, title cleanup, local lookup, OL works, Google Books, covers, fingerprint, …). A
single `processing_status` cannot say "OCR failed, enrichment succeeded, fingerprint pending".
Today that state is scattered across JSONB markers (`local_enriched`, `local_title_tried`,
`ol_works_tried`, `isbn_ocr_tried`, `title_parsed`, …). On fides those markers **failed open**: a
few rows' `extra_metadata` had degraded from an object into a JSON array (Postgres `||` coerces to
array concatenation when either side is not an object), after which `extra_metadata ? 'title_parsed'`
tested array membership, never matched, and a loop re-processed and re-appended to the same row
every tick (one row had accumulated dozens of copies of `{"title_parsed": true}`). Proposal:
- `book_pipeline_state(book_id, pipeline, status, attempts, last_error, next_retry_at, updated_at,
  PRIMARY KEY (book_id, pipeline))` with exponential backoff and a max-attempts cut-off — this is
  what "never retry forever" actually needs, per pipeline.
- `ALTER TABLE books ADD CONSTRAINT extra_metadata_is_object CHECK (jsonb_typeof(extra_metadata) = 'object')`
  to make the whole corruption class impossible.
- Make ineligibility explicit: books with empty or whitespace-only titles were silently skipped by
  every `length(title) > N` guard (a PDF metadata title of `" "` defeated the filename fallback) and
  never entered any pipeline.

**4.9 M10 — the missing piece is loop visibility.** The breaker and health endpoint largely exist
(§2). What does not exist is any view of the ~13–16 scheduler loops. On fides, loops failed on every
tick for months without a trace outside the log stream: eight loops importing six modules absent
from `main` (`text_profiler`, `ocr_copyright`, `cover_phash`, `metadata_validator`, `confidence`,
and `ol_local` for the two `fast_local` loops and `ol_works`; `ModuleNotFoundError` swallowed by
`_supervised`), `fast_local` crashing on the JSONB shape above,
`_google_books_loop` crashing on a missing module attribute. A per-loop heartbeat
(`last_run_at, last_ok_at, last_error, consecutive_errors`) exposed in `/health` — degraded when a
loop has not succeeded in N intervals — would have surfaced every one of them on day one. Cheap,
high value, P0.

**4.10 Other master tasks.**
- **M2** — correct, but it is a bug fix (§2). Use the table name the code already uses (`reading_log`).
- **M3** — unification with library-vision B5 is a good call; start from the existing
  `/summary` and `/goldmine` routes. Decide storage policy (Open Question 2) before building.
- **M4** — LoC part done; the per-book enrichment explanation is genuinely valuable for trust and
  debugging, and cheap if `enrichment_log` is extended with the merge decision (it already records
  source and success).
- **M6/M7** — mostly UI wiring; small.
- **M8** — agree it is gated. Recommend explicitly deciding "single-owner / family" now; it unblocks
  everything else and matches reality.
- **M11** — GHCR images: high adoption value, low effort; independent of the rest.
- **M12** — include the Calibre `ImportError` (§3.5) and the schema-vs-code audit (§2).

### 4.11–4.15 `library-vision.md`

**Owned summaries — value and feasibility.** For this owner, who holds getAbstract/Blinkist
summaries, "read the summary first" is a real time-saver and a genuine differentiator; for general
users it is a niche. Feasibility is good for text summaries: getAbstract PDFs carry stable
boilerplate, and summary titles usually match the original title, so `identify.same_title` works.

**4.11 Centralize the gate instead of listing call sites.** All 13 call sites in A2 exist, but the
list is incomplete. Missing: `metadata.enrich_book` / `_enrichment_loop` itself,
`_google_books_loop`, `_cover_loop`, `format_stack.auto_stack_cycle`, `intelligence.find_duplicates`
and `series_suggestions`, `incipit_match`, `organize.organize_after_enrichment` and
`experimental/file_rename.rename_book_file` (would move/rename summary files), and the two that act
outside the system: **`writeback.writeback_metadata`** (writes metadata into the summary file) and
**`contribute.contribute_back`** (submits metadata to **Open Library** — a misidentified summary
would pollute a public database). *Correction (round 4): today `contribute_back` is a dry run — it
only reads Open Library and records `can_contribute_to_ol`; nothing is submitted. The gate matters
once the planned writeback (R2.11.18) is built.* A hand-maintained list will drift. Better: one
`eligible_books(pipeline)` view or helper that every candidate query uses, plus a unit test that
fails when a pipeline module selects `FROM books` without it. Fold the existing
`books.is_workbook` flag (migration 002) into `content_type` (`'workbook'`), since it is the same
idea.

**4.12 Audio summaries have no text.** B1 samples "first and last N pages"; a Blinkist MP3 has none.
Use ID3/M4B tags (artist/album/publisher), then filename/folder rules — the existing
`consumption_rules.apply_rules` hook already supports folder/filename conditions, e.g.
`incoming/summaries/<provider>/` — and only then STT of the first seconds via Intello. In B3, require
author-surname agreement in addition to `same_title`; summary titles are often generic ("The Power
of Habit" vs. a dozen summaries of it).

**4.13 Sequencing.** Phase B is the headline, but its value is concentrated on one user and it
depends on A2 being complete. Do the gate (as a view) early, B later than P0/P1 correctness work.

**4.14 Offline reference DBs — proven feasible, needs a disk budget, misses the best source.**
Measured on fides for the OL editions dump: 12.6 GB download → 14 GB SQLite, 56.7 M editions,
46.7 M ISBNs, ~63 min single-threaded import, working `fast_local` ISBN lookups immediately after. So the `disk_budget` field in C2 is not optional. Assessment per source:

| Source | Value for identifying owned books | Cost | Verdict |
|---|---|---|---|
| OpenLibrary editions | High | 12.6 GB + 14 GB index | Keep — pick **one** of the two implementations (author's, with BnF SPARQL; fides', with `work_key` and a built index) |
| OpenLibrary works | Medium–high (descriptions, subjects) | 4.1 GB download + index | Add — removes `ol_works`' per-book network calls |
| BnF | High for the ~30–40% French content | moderate | Keep |
| DNB | Medium (German content) | moderate, open data dumps | Add |
| **LibGen / Anna's Archive metadata (MD5-keyed)** | **Highest for this corpus** — most incoming filenames end in `libgen.li` / `Anna's Archive`; an exact file-hash lookup identifies without fuzzy matching | several GB | **Missing from R3.** Metadata only, but needs an explicit legal/ethical decision by the owner |
| Gutendex, Standard Ebooks, Packt, Open Textbooks | Low for identification (public-domain/free catalogs — discovery, not identification) | small | Park |
| Wikidata | Low per GB | very large | Agree: off by default |
| Google Books | — | API only | Agree: excluded |

**4.15 Semantic embeddings (C4).** `config.embedding_model` already names
`paraphrase-multilingual-MiniLM-L12-v2` (384-d, matches the `vector(384)` column): local, CPU-feasible
at this scale, and — being multilingual — a direct signal for the translation class in §4.2. Higher
value than the PR assigns it.

**C5** (recommendation categories): correct diagnosis, low priority.

### 4.16–4.17 `ai-in-app.md`

**Diagnosis: valid.** A context-blind keyword classifier one HTTP hop away cannot know that an
`ocr_cleanup` call wants the cheapest model and an `ask_book` call wants a good one. The task-intent
enum is the right abstraction.

**4.16 Remedy: oversized.** Porting Intello's router (provider catalog, scoring, AIMD, rate limits,
cost ledger, cross-session learning) into BrainyCat duplicates a gateway that already serves several
projects, and splits budgets and the ledger per app — losing the cross-project budget enforcement
Intello exists for. Cheaper, higher-value path:
- **AI0 — consolidate the in-app call sites first.** LLM calls are scattered today:
  `companion._llm`, `translators/llm.py`, `worddumb`, the summary/goldmine routes, plus
  `translators/ollama.py` and `deepl.py` which are advertised but not wired (§3.7). One
  `ai.complete(intent, prompt, …)` interface is needed whatever routing you choose.
- **AI1′ — send the intent to Intello.** Extend Intello's API with explicit
  `intent / tier / max_cost / latency` hints that bypass `classify_task`. This fixes the context
  problem in a fraction of the code and keeps one ledger.
- Build the in-app router (AI1–AI7) only if Intello cannot be changed.

**4.17 Charter tension — principle 6.** "Self-hosted sovereignty — no cloud dependencies" sits
uneasily with direct calls to Groq / Google / DeepSeek / OpenAI / xAI carrying book text. Proposal:
local-first by default (Ollama is already listed), cloud providers opt-in **per intent**, and never
send full book text to a cloud provider unless the owner explicitly enables it for that intent.
**Secrets:** keep keys in the existing gitignored `.env` (or Docker secrets), not a `secrets.md` at
the repo root — Markdown files get read, indexed, previewed and committed routinely.

### 4.18 `onboarding.md`, `user-journeys.md`, `selfhosted-post.md`, `backlog.md`

- **onboarding.md** — useful; fix the unmerged references (§3.6). The "gate automated writes on
  per-book state" convention is exactly right and should cite the central view once it exists.
- **user-journeys.md** (UJ-34…38) — clear and testable; UJ-34 should cover the audio path (§4.12).
- **selfhosted-post.md** — a "coming soon" for an unbuilt feature that names Blinkist and
  getAbstract is premature; both services' terms typically restrict exporting content. Suggest
  "summaries you own as files" with no provider names until checked.
- **backlog.md** — valuable as a single list; re-grade per §2 and §7 (M2 schema → P0; M4-LoC → done;
  M5/M6/M7 → small UI tasks; add the Phase 0/1 items).

---

## 5. Charter alignment

| Principle | library-vision | dedup-overhaul | master plan | ai-in-app |
|---|---|---|---|---|
| 1. AI-first, graceful degradation | ✅ B5/C4 hide without Intello | ✅ fully local | ✅ M10 | ✅ degraded mode |
| 2. One entry, multiple formats | ✅ C1 editions | ⚠️ conflates format with edition (§4.2) | — | — |
| 3. Continuous enrichment | ✅ local-first dispatch | — | ⚠️ M1 as one column can't express per-pipeline retry (§4.8) | ✅ |
| 4. Experimental framework | ✅ fixture tests for B1 | ✅ labeled pairs — go further: **fit** the weights (§4.1) | ⚠️ "recovered" items not measured against what exists (§2) | ✅ AI5 before/after |
| 5. Protocol polyglot | — | — | ✅ Readwise, kosync tracked | — |
| 6. Self-hosted sovereignty | ✅ dumps only, no scraping | ✅ | ✅ | ⚠️ cloud providers by default (§4.17) |

---

## 6. Value / effort / feasibility

Value: H/M/L to this library's owner. Effort: S (≤1 day) / M (days) / L (week+).

| Item | Value | Effort | Feasibility | State in `main` | Verdict |
|---|---|---|---|---|---|
| M1 per-pipeline state + JSONB CHECK | H | M | high | scattered markers | **Reshape** (§4.8), P0 |
| M2 status/log schema | H | S | high | routes exist, schema missing (streak works) | **Do now** as bug fix |
| M3 intelligence/goldmine | M | M | needs Intello | routes exist | Merge with B5 |
| M4 enrichment explanation | M | S | high | LoC done | Do (explanation only) |
| M5 Word Wise / X-Ray UI | L–M | S | needs Intello | routes exist | UI only, P2 |
| M6 check-owned / FTS snippets | M | S | high | routes exist | UI wiring, P1 |
| M7 bulk editor | M | S–M | high | tag-only | Extend, P2 |
| M8 multi-user | L (today) | L | high | — | Decide single-owner; park |
| M9 DNA / wrap-up | L | S | high | experimental | After M2 |
| M10 loop heartbeat | **H** | S | high | health exists | **Do now**, P0 |
| M11 GHCR / metrics | M–H | S | high | — | Do anytime |
| M12 tests + Calibre ImportError + schema audit | H | S–M | high | broken | P0 |
| A1–A3 content_type + central gate | M | M | high | `is_workbook` precedent | Do, with view (§4.11) |
| B1–B4 owned summaries | H (this owner) | M | high (text), medium (audio) | — | Do after P0/P1 |
| B5 self summaries | M | M | needs Intello | `/goldmine` exists | Merge with M3 |
| B6 MCP summaries | L | S | high | — | Later |
| C1 editions grouping | M–H | M | high with OL `work_key` | `book_links` exists | Do with D5 |
| C2 offline registry | H | M–L | proven | two unmerged impls | Reconcile first, add disk budget |
| C2+ LibGen/AA MD5 metadata | **H** | M | high | — | Owner decision |
| C4 multilingual embeddings | M–H | M | high | TF-IDF hash | Raise priority (translations) |
| C5 reco categories | L | M | high | stub | Park |
| D1 size ratio + fuzzy skeleton + cursor | H | S | high | defects confirmed | **Do now** |
| D2 cover pHash | M | M | high (Pillow) | stub in author's tree | Do |
| D3 LSH bands in Postgres | H | M | high (signature is positional) | experimental | Do, persistent (§4.6) |
| D4 fused scorer | H | M | high | — | Fix rubric; fit weights (§4.1) |
| D5 routing | H | M | high | `format_stack` | Add stack/translation classes (§4.2) |
| D6 review queue | H | M | high | built on fides | Merge fides UI (§4.3) |
| D7 coverage guarantee | M | S | high | audit script | Do |
| `book_files.sha256` | H | S | high | — | Add (§4.5) |
| CPU off the event loop | H | S–M | high | blocking today | Prerequisite (§4.7) |
| AI0 consolidate call sites | M–H | S–M | high | scattered, 3 dead backends | **Do first** |
| AI1′ intent hints to Intello | M–H | S | high | — | Prefer over AI1–AI7 |
| AI1–AI7 in-app router | M | L | high | — | Only if Intello can't change |

---

## 7. Recommended sequencing

**Phase 0 — land and reconcile (prerequisite).**
- Land the author's local tree: `offline_bootstrap.py`, `ol_local.py`, `cover_phash.py`,
  `text_profiler.py`, embeddings, `devdocs/`.
- Land the fides working tree (≈92 files): second `ol_local.py` + built index, scheduler changes
  (`_fingerprint_loop`, `_log_retention_loop`, silenced loops), dedup recommendation UI,
  `intelligence` title normalization and series de-duplication, `extract._blank_to_none`, file-rename
  wiring with the unresolved-title guard, PDF quick-browse viewer, 369 docstrings.
- Choose one `ol_local` (merge BnF SPARQL from the author's with `work_key` from fides').
- Correct `docs/known-issues.md` entries written on fides that call `text_profiler` / `cover_phash` /
  `ocr_copyright` / `metadata_validator` / `confidence` "never implemented" — per this PR they exist,
  just not in `main`.
- Fix the `_fingerprint_loop` re-scan of the same 20 books (§3.4).

**Phase 1 — correctness and observability (P0).**
Loop heartbeat in `/health` · schema-vs-code audit + M2 migrations · `book_pipeline_state` +
`extra_metadata` CHECK · `book_files.sha256` · D1 with a cursor · Calibre `ImportError` + test
collection · CPU-bound work off the event loop.

**Phase 2 — dedup that works.**
D3 (persistent bands) → D4 (renormalized, fitted fusion) → D5 (exact / stack / edition / translation)
→ D6 (single queue, keep-recommendation, space sorting) → D7 → retire the overlapping paths (§4.4).

**Phase 3 — content types and owned summaries.**
`content_type` with the central eligibility view and `is_workbook` folded in → B1–B4 with the audio
path → B5 merged with M3.

**Phase 4 — breadth.**
Offline registry with disk budgets (OL works, DNB; LibGen/AA metadata if approved) → multilingual
embeddings → AI0 → AI1′ (or the in-app router if Intello cannot change) → UI wiring of M5/M6/M7.

**Unchanged:** P3 parking lot. **Decide now:** M8 single-owner, M3/M5 storage policy, M11 timing,
LibGen/AA metadata.

---

## 8. Measurements to run before committing (charter principle 4)

1. **Sentence identification hit rate.** `sentence_match` (Google Books full-text) on the sample
   pools saved on fides — `/mnt/buffer/brainycat/data/known_pool.tsv` (400 books with a trusted ISBN)
   and `unknown_pool.tsv` (100 with unresolved titles). Success on the known pool = returned ISBN or
   title/author matches the known one. `sentence_match` issues up to two queries per book, so the
   500-book run fits the default Google Books quota (1,000 requests/day) over one to two days. Also try
   the stricter sentence picker prototyped on fides
   (`/mnt/buffer/brainycat/data/pilot_extract_sentences.py`: 5–25% position, 12–35 words, terminal
   punctuation, stopword density < 60%, internal clause punctuation) against the current "fewest
   common words" picker.
2. **Labeled dedup pairs for D4/D5.** Build from real data on fides: the metadata duplicate pairs
   (~3.7 K), content matches as fingerprint coverage grows, and user decisions from the review UI.
   Note: the fides copy of `golden_corpus` was folded into the library during the 2026-09-30 session
   at the owner's request; the labeled manifest (`tests/golden/manifest.yaml`) must reference the
   ecb.pm copy or book IDs.
3. **Dedup baseline timings.** Record current `find_duplicates` / `find_duplicates_by_content` wall
   time and API responsiveness at the real library size, so DR1's budget is a measured improvement.

---

## 9. Open decisions for the owner

1. Single-owner vs multi-tenant (M8).
2. Stored vs on-demand LLM content (M3/M5) and its disk/Intello budget.
3. LibGen / Anna's Archive metadata dumps as an identification source (metadata only).
4. AI routing: extend Intello with intent hints (recommended) vs in-app router; cloud providers
   opt-in per intent.
5. Which `ol_local` implementation survives.
6. Public GHCR images now or after the UI redesign (M11).
