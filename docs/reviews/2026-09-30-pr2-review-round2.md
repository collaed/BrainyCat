# Review, round 2 — response to the response (PR #2)

> Follow-up to [`2026-09-30-pr2-roadmap-review.md`](./2026-09-30-pr2-roadmap-review.md), covering
> commit `a475ec8`: [`2026-09-30-pr2-review-response.md`](./2026-09-30-pr2-review-response.md), the
> new [`../roadmap/decisions-and-code.md`](../roadmap/decisions-and-code.md), and the edits to the
> dedup, master, AI, backlog, onboarding and marketing docs. Same method as round 1: every code
> example was checked against `main` and the fides schema.

## Summary

The response is a good one. It records a disposition for every point, and the owner decisions
(Phase 0 first, in-app AI routing, a trusted-group multi-user model, stored LLM content with a
6-month refresh, LibGen/AA metadata, GHCR deferred, one reconciled `ol_local`, trust rule D) are
clear and are the owner's to make. Nothing below reopens them.

`decisions-and-code.md` is new code-level material, and it needs the same scrutiny the plans got.
The most important finding is in the P0 item itself: **the M2 migration, as written, would not make
the broken routes work.** It invents column names and a status value that the existing code does
not use. That is the exact mistake the migration was meant to fix. A few other examples have
defects that would mislabel the most common duplicate case, flood candidate generation, or apply
contradicting edits to shared metadata. All of them are fixable in the document before anyone
implements from it.

There is also one bookkeeping gap. The response says `library-vision.md` and `user-journeys.md`
were updated (central gate, audio path, author-surname rule, disk budgets, LibGen/AA, embeddings,
multi-user, stored LLM content, UJ-34), but commit `a475ec8` does not touch either file. They still
describe the pre-review design, so the doc set now contradicts itself.

## Findings

Severity: **blocker** = the example would fail or corrupt data if implemented as written;
**major** = wrong behaviour in a common case; **minor** = convention or robustness.

### M2 — the P0 fix would still fail (blocker)
The migration must match what `routes/reader.py` and `experimental/book_dna.py` already use:

| | Code in `main` uses | Proposed migration | Effect |
|---|---|---|---|
| status value | `library` (`reader.py:428–429`, route default) | `library_only` in the CHECK | `PUT /books/{id}/status` with the default status → CHECK violation |
| minutes column | `minutes` (`reader.py:561`, `:582`, `:678`, `:823`; `book_dna.py:30`) | `minutes_read` | every read and insert → UndefinedColumn |
| timestamp column | `logged_at` (same lines) | `date` | same |
| `book_id` | route inserts `NULL` when no book is given | `NOT NULL` | NOT NULL violation |
| uniqueness | plain `INSERT`, several sessions per day | `UNIQUE (user_id, book_id, date)` | second session of the day → unique violation |

Corrected shape:
`reading_log(id, user_id NOT NULL, book_id NULL, minutes INT, pages_read INT, logged_at TIMESTAMPTZ DEFAULT now())`,
with no unique constraint, plus `reading_progress.status` accepting `library`. Make this migration
**012**. It is the smallest and most urgent, and right now 012 is claimed twice (M1 and content types).

### M1 — `book_pipeline_state` (major)
- **Rows are never seeded.** `claim()` only picks existing `pending/failed` rows, and nothing inserts
  them for new books, so pipelines would find no work. Either seed pending rows on ingest, or claim
  from `eligible_books LEFT JOIN book_pipeline_state`, treating a missing row as pending.
- **`processing` rows can be stranded.** A crash or container restart mid-run (frequent on fides)
  leaves rows in `processing` forever. Add a `claimed_at` lease and reclaim stale rows, or reset
  `processing` to `pending` at startup.
- Minor: `ADD CONSTRAINT … NOT VALID` isn't idempotent (Postgres has no `ADD CONSTRAINT IF NOT
  EXISTS`); guard it with a `DO $$ … IF NOT EXISTS (SELECT 1 FROM pg_constraint …) $$`. fides
  currently has 0 non-object rows, so `VALIDATE` can run right away there. The backoff table lives
  twice (Python `BACKOFF` and the SQL array); keep one.

### M10 — heartbeat (major, easy fix)
A fixed 3,600 s staleness threshold marks `log_retention` (86,400 s interval) and `isbn_extract`
(3,600 s interval) as permanently stale, so `/health` would always report degraded. `isbn_extract`
also starts once and loops internally, so its tick never returns and never records success. Use a
per-loop threshold (e.g. 3× the loop's interval) and have long-running workers call `record()` from
inside their own loop.

### A2 — `eligible_books` view and enforcing test (major)
- **A view can't express per-pipeline eligibility.** Identity-rewriting pipelines (title cleanup,
  ISBN extraction, `sentence_match._apply_match`, the `fast_local` title pass) must also skip
  `identity_status = 'protected'`; that is PR #1's "enrichment may add, but not change identity".
  The view only excludes `locked`, so it would clobber manual fixes. Use two views
  (`enrichable_books`, `identifiable_books`) or a function taking the pipeline name.
- **`SELECT b.*` is frozen when the view is created.** Columns added later (`owner_id`,
  `canonical_id`, `visibility` in migration 014) won't appear until the view is recreated. List
  columns explicitly, or recreate the view in every migration that alters `books`.
- **With multi-user, eligibility must include `canonical_id IS NULL`.** Otherwise enrichment runs
  once per virtual copy and the copies drift apart.
- **The test fails on day one and misses the busiest module.** The regex flags every `FROM books`,
  including legitimate single-row fetches (`WHERE id = $1`, which `metadata.py` alone has many of),
  and it has no allowlist, so it will be disabled. Meanwhile `scheduler.py`, where the
  `_google_books_loop`, `_cover_loop` and `_isbn_worker` candidate queries live, is not in
  `PIPELINE_MODULES`. Suggest an explicit marker (`-- pipeline-candidate`) that the test requires to
  be paired with `eligible_books`.
- **`writeback_metadata` and `contribute_back` don't select candidate lists.** They receive a
  `book_id`. They need an explicit `content_type` check on the fetched row; the view alone won't
  gate them.

### Content types and stored LLM content (major)
- **Existing summaries live in `books.extra_metadata->'summary'`** (`summaries.py:117/189`). Without
  a data migration into `ai_content`, they are orphaned and there are two stores.
- **Six-month refresh is time-only.** Also store `prompt_version` and the source file hash, so
  content goes stale when the prompt changes or the text changes (a stack or merge), not only when
  it ages.
- **Per-user versus shared.** `UNIQUE(book_id, kind)` fits shared kinds (goldmine, X-Ray). Per-user
  kinds (`ask_book`, `recap`) need `user_id` in the key once multi-user lands.
- **`'stack'` in the `book_links` CHECK contradicts §D5.** Stacking means one book with two files,
  not a link between two books. Drop it, or document it as a transitional link.
- **Folding in `is_workbook`** also needs `UPDATE books SET content_type='workbook' WHERE is_workbook`
  plus a switch in `convert.py:114–124`, which reads the flag.

### MT — multi-user (major)
- **Virtual `books` rows versus membership.** If metadata is shared anyway, a virtual copy row per
  user duplicates every metadata column and forces every query through `canonical_id`. A membership
  table `user_library(user_id, book_id, added_at, visibility)` over one canonical `books` row is
  simpler and can't drift. Per-user state already keys on `(user_id, book_id)`.
- **Upload race.** Two concurrent uploads of the same file both miss the lookup and create two
  canonicals. This needs a unique index on the file hash (partial, on canonical rows) and
  `ON CONFLICT`. The proposed `book_files_sha256_idx` isn't unique.
- **Trust rule D, as coded, is close to the inverse of the stated rule.** `contradicts` requires the
  undefined `_is_downgrade()`. When it returns false, a user replacing a trusted value with a
  different, uncorroborated one falls through to "neutral → apply". Worked example 3
  ("Sapiens" → "Sapiens (my notes)") is only queued if `_is_downgrade` happens to say so. Define
  "neutral" narrowly (whitespace or case only) and queue any uncorroborated change to a non-empty
  value that is trusted (corroborated, or `identity_status` protected/locked).
- **Allowlist `field`.** `book[field]` and `_apply_canonical(…, field, …)` take the field from the
  request. The repo convention in CLAUDE.md is that dynamic column names come from a module-level
  allowlist.
- **`/books/{id}/override` becomes dangerous once metadata is shared.** It clears tags, categories
  and enrichment history. One non-admin "Fix misidentified" would wipe shared data for everyone, so
  route non-admin overrides through the queue.
- **sha256 catches only byte-identical files.** Different scans of the same edition still create
  separate canonicals, so "no duplicate book files" also depends on the dedup pipeline (the
  duplicate-copy class below).

### Hashing, LibGen/AA and cross-user dedup — hash the original bytes (blocker for MT and LibGen)
`watcher._import_file` calls `fix_epub(dst)`, which rewrites the EPUB in place at ingest whenever
it applies a fix (`epub_fix.py`: `os.replace(tmp_path, epub_path)` if any fixes).
`writeback_metadata` later rewrites EPUB OPFs and incrementally saves PDFs (`writeback.py:74`,
`:163`). So an MD5 or sha256 of the **stored** file:
- will not match the LibGen/AA record, which is the MD5 of the original download;
- will not match the next user's upload of the same original file, which breaks MT dedup.

Hash the **original bytes at ingest, before `fix_epub`**, and store them immutably
(e.g. `book_files.original_md5`, `original_sha256`). A separate current-content hash can serve
integrity checks. A free bonus: 1,122 of the 3,949 files on fides (28%) carry the Anna's Archive
MD5 in their filename (`… -- <32 hex> -- Anna's Archive.epub`). Extract it into a column at ingest,
because the filename-standardizing rename (fides tree) drops it. `filename_history` keeps the old
names, so it can be backfilled.

### D3 — persistent bands (major)
Books with empty or very short fingerprints (image-only PDFs, which this library has many of) all
produce the same signature, so every one of their 32 bands lands in the same bucket and the
self-join emits every pair among them. Exclude books below a minimum k-gram count from banding;
route them to the image/cover path instead. Also cap bucket size and log oversized buckets, since
boilerplate-heavy families (same publisher template) cause the same blow-up on a smaller scale.

### D4 — fusion (major)
- **Renormalizing without minimum evidence inflates weak pairs.** With only `title_author_sim`
  and `size_ratio` present (common: coverage gaps mean no MinHash, often no cover pHash), two volumes
  of a series (title sim ≈ 0.9, similar size) fuse to
  (0.20·0.9 + 0.05·0.95)/0.25 ≈ **0.91** and land in "probable duplicate". That is the
  series-as-duplicates confusion fixed on fides this week. Require a minimum present weight (or
  shrink toward a prior), and keep the numeric-token series guard from
  `intelligence.find_duplicates`. A logistic model with missing-value indicators handles this
  naturally; the weighted mean needs the guard.
- **Different ISBNs are evidence too.** `isbn_signal` returns `None` both when ISBNs are missing
  and when they differ. Two valid, non-shared, different ISBNs are evidence of *different
  editions*. Return 0.0 in that case; D5 needs the distinction.
- **`reject_shared(a.isbn)` doesn't match the real API.** `identify.reject_shared(cands, titles)`
  (`identify.py:106`) is batch-oriented and returns a list. Precompute a shared-ISBN set (ISBN →
  more than k distinct normalized titles) and test membership.

### D5 — classification (blocker for the most common case)
- **No class for "same edition, same format, different file".** In this library, that is the most
  frequent real duplicate: two libgen/Anna's Archive downloads of the same EPUB, not byte-identical.
  Same ISBN (or `same_work`) plus the same format skips the stack branch, fails the translation
  test, and falls to **`other_edition`**. The pair gets linked as an edition instead of offered for
  deletion. Add `duplicate_copy`: same work, same format, high MinHash or close size → keep the best
  copy (the fides keep-recommendation) and delete the other.
- **Equal ISBNs mean the same edition.** `same_work` via `isbn_signal == 1.0` can never be
  "other edition" (placeholder ISBNs are already filtered out).
- **The translation test lacks same-work evidence.** Different-language books on the same topic
  (this library has several French/English books on the same subjects) easily reach multilingual
  cosine ≥ 0.75. Require `same_work` (OL `work_key`, or a matching author plus translated title)
  and different `language`, not cosine alone.
- `a.format` is ambiguous for books that already have several files. Classify on file pairs, or on
  format sets.

### CPU off the event loop (minor)
`asyncio.to_thread` keeps the event loop responsive (the GIL switches every 5 ms), but pure-Python
scoring gains no parallelism and slows the API while it runs. For full-library runs, prefer a
process pool or the separate worker. Also, the function passed to the thread must not touch the
asyncpg pool: fetch rows first, score in the thread, write after.

### AI — in-app routing (owner decision respected; notes)
- **Define "full text".** `ASK_BOOK` needs excerpts (RAG chunks), and `allow_full_text=False` either
  blocks it or is meaningless depending on the definition. Specify a size (e.g. at most N tokens of
  excerpts per call) and pass book text only as a structured argument, so text embedded in `prompt`
  can't bypass the guard.
- **`GOLDMINE` is local-only.** Measure local-model throughput on fides first. Whole-book
  summarization of about 3,900 books on CPU with a capable model may take weeks. Allow an explicit
  per-book cloud opt-in, or batch it, rather than discovering this after building.
- **One ledger covers BrainyCat only.** It preserves BrainyCat's budgets, but other projects still
  spend through Intello, so a global cap needs one ledger to report to the other. The owner's call;
  noted so it's a known limit, not a surprise.

### Docs
- `library-vision.md` and `user-journeys.md` weren't changed despite the response's "What changes"
  list. Apply the edits, or add the same "superseded by decisions-and-code" banner the other docs got.
- `review-response.md:34` mentions the location of the owner's consolidated secrets file. The repo
  is **public**; suggest removing the path. It tells a reader where everything is kept.
- The repo is also public for the LibGen/AA decision. Suggest describing it as "hash-keyed
  bibliographic metadata", off by default, enabled per instance, which the code sketch already
  implies.

## Suggested next step
Fix the two blockers in `decisions-and-code.md` (the M2 migration shape; D5's missing
duplicate-copy class) and the original-bytes hashing, since MT and LibGen both depend on it. Then
land the Phase 0 reconciliation. With M2 corrected, it can ship as migration 012 on its own, ahead
of everything else: one small migration, three broken routes fixed.
