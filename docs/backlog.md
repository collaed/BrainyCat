# BrainyCat — Backlog

> Single prioritized backlog. It consolidates the Ideas Parking Lot from `roadmap.md`, the recovered
> ideas from `roadmap/master-improvement-plan.md` (M1–M12), `roadmap/library-vision.md` (A/B/C),
> `roadmap/dedup-overhaul.md` (D1–D8) and `roadmap/ai-in-app.md` (AI0–AI8). It also tracks **every
> known issue** (`known-issues.md`, `honest-status.md`, the caveats in `CLAUDE.md`, and the PR #2
> reviews) as a `K#` item — see [Known-issue coverage](#known-issue-coverage) at the end.
>
> **2026-09-30 re-grade.** The tables below reflect the PR #2 review and the owner's decisions
> ([response](./reviews/2026-09-30-pr2-review-response.md),
> [decisions-and-code](./roadmap/decisions-and-code.md)). Main changes from the original backlog:
> M2's schema is now a P0 bug fix; M4's LoC removal is done; M5/M6/M7 are small UI tasks; multi-user
> (M8) is in scope; GHCR images (M11) are deferred; the LibGen/AA MD5 metadata source is added; and a
> Phase 0 lands and reconciles the unmerged code first.

## Legend

- **Phase 0** — prerequisite: land and reconcile code that lives outside `main`.
- **P0** — correctness, security, reliability, data-loss prevention. Do first.
- **P1** — high user-visible value, or cheap fixes to things visibly broken.
- **P2** — valuable, sequenced after P0/P1.
- **P3** — parked; do when relevant or when a dependency lands.
- **Deferred** — decided "not now", with a reason.
- **Done** — kept briefly so the history of known issues is traceable.

## Phase 0 — Land and reconcile (prerequisite)

| ID | Item | Source | Notes |
|----|------|--------|-------|
| L1 | Land the author's local tree: `offline_bootstrap.py`, `ol_local.py`, `cover_phash.py`, `text_profiler.py`, `ocr_copyright`, `metadata_validator`, `confidence`, `incipit_match`, the embeddings pipeline, `devdocs/` | review §1, §7 | The scheduler in `main` imports these modules; without them, their loops fail every tick (M10 makes that visible). |
| L2 | Reconcile the two `ol_local.py` implementations: keep the author's BnF SPARQL plus fides' `work_key` column and the built 14 GB index | review §4.14 | fides' version landed in `main` with `f02f7cf`. |
| L3 | Rewire the scheduler once L1 lands: restore the real `text_profiler` / `cover_phash` / … loops and re-check the `_fingerprint_loop` stand-in added in `f02f7cf` | review §3.4 | Its batch re-scan is fixed by D1's cursor. |
| L4 | Correct `known-issues.md`: the "loops call modules that were never implemented" entry is wrong — the modules exist outside `main` | review §7 | Doc-only. |

## P0 — Correctness, security & reliability

| ID | Item | Source | Notes |
|----|------|--------|-------|
| K1 | **Auth hardening:** stop trusting `X-Auth-User` unless the request comes from a configured trusted proxy (`BRAINYCAT_TRUSTED_PROXIES`); verify the `ecb_auth` cookie signature; stop auto-creating users (and granting `admin` to `ecb`) from an unauthenticated header | CLAUDE.md (auth) | Today fides serves `:8950` directly on the LAN with no proxy, so any client on the network can send `X-Auth-User: ecb` and become admin. Blocks M8: multi-user makes this a cross-user issue. |
| M2 | Reading-status and reading-log schema, so the existing routes stop returning 500 | review §2; round 2 | Use the columns and values the code already uses (`reading_log.minutes/logged_at`, nullable `book_id`, status `library`). Ship alone as migration 012. |
| K2 | Fix `series_detect.py:57`: it inserts `books_series.series_index`, but that column is on `books` | fides logs | Seen as `format_stack_error: column "series_index" of relation "books_series" does not exist`. |
| M10 | Per-loop heartbeat in `/health` (last run, last success, last error, consecutive errors; threshold per loop interval) | review §4.9 | `/health` and the rate-limit breaker already exist; loop visibility is what's missing. |
| M1 | `book_pipeline_state` (per book × pipeline: status, attempts, backoff, lease) + `CHECK (jsonb_typeof(extra_metadata)='object')` | review §4.8; round 2 | Replaces the scattered JSONB "tried" markers. Also covers K3. |
| K3 | Harden the remaining `extra_metadata = COALESCE(extra_metadata,'{}') \|\| $1::jsonb` writers (`title_cleanup`, `metadata`, `bisac`, `worddumb`, `contribute`, `readability`, `routes/books`, `scheduler`) until the CHECK constraint is validated | known-issues.md | `fast_local` is already hardened (`f02f7cf`). |
| M12 | Test and schema health: Calibre `detect_calibre_library` `ImportError` (a runtime failure in `routes/admin.py`, and the reason `test_calibre.py` / `test_epub_check.py` don't collect); schema-vs-code audit; align `--cov-fail-under=80` with real coverage (~21%) so the default `pytest` run is meaningful | review §3.5, §2; CLAUDE.md | The audit catches the whole phantom-schema class (`original_filename`, `reading_log`, K2). |
| K4 | Fix the duplicate route definitions in `routes/admin.py`: `import_calibre` ×3 and `import_goodreads` ×2 (ruff F811) | ruff baseline | Two of the three `import_calibre` handlers are dead or shadowed; decide which one is live. |
| D1 | Dedup correctness: add a cursor to `find_duplicates_by_content` (today it re-compares the same first `batch_size` books every run), use the discarded size ratio, fuzzy skeleton match | review §3.4 | Also resolves the re-scan in `_fingerprint_loop`. |
| K5 | CPU-bound work off the event loop: `intelligence.find_duplicates` (50–60 s at 3.9 K books, API unresponsive), fingerprint scoring, `fitz` page rendering in request handlers | review §4.7 | `asyncio.to_thread` for request paths; a process pool or worker for full-library runs. |
| K6 | Hash **original bytes** at ingest, before `fix_epub` modifies the file (`original_md5`, `original_sha256`); extract the Anna's Archive MD5 from filenames before the standardizing rename drops it (1,122 / 3,949 files) | round 2; decisions-and-code | Prerequisite for exact dedup, multi-user file sharing and the LibGen/AA source. Backfill filenames from `filename_history`. |

## P1 — High user-visible value / visible breakage

| ID | Item | Source | Notes |
|----|------|--------|-------|
| K7 | Incoming folder: move files that can't be imported (unsupported type, 0 bytes, corrupt) to `incoming/_rejected/` with a reason, and list them on the Incoming page | fides incoming | Today they stay forever with no feedback: 1,745 `.jpg`, 13 zero-byte `.pdf` and 1 `.wav` left over from the 2026-09-29 reingest. |
| K8 | Stop advertising translation backends that aren't implemented: `list_backends()` offers DeepL, Google and Ollama, but `_get_backend()` returns `None` for all three | docstring pass; review §3.7 | Implement them via AI0 or remove them from the list. |
| K9 | Quarantine corrupt files: on a MuPDF/zlib failure, mark the file failed (M1) instead of re-parsing it on every pass | fides logs | 16,058 `MuPDF error` lines in 24 h. |
| A2 | Central eligibility gates (`enrichable_books`, `identifiable_books`) plus a marker-based enforcing test; explicit `content_type` checks in `writeback_metadata` and `contribute_back` | review §4.11; round 2 | Protects summaries and manually fixed books. |
| A1 | Migration: `content_type` (folding in `is_workbook`) + `book_summaries` | library-vision | Foundation for summaries. |
| B1–B4 | Owned summaries: detect (text, plus the tags/folder path for audio) → ingest → auto-link (author-surname agreement) → summary-first reading | library-vision | Headline payoff for the owner. |
| D3 | Persistent LSH bands in Postgres (`minhash_bands`, 32×4), skipping empty or short fingerprints | review §4.6 | Library is ~3.9 K books (not 63 K). |
| D4 | Fused scorer, renormalized over present signals, with a minimum-evidence floor and the series guard; weights fitted on labeled pairs | review §4.1; round 2 | |
| D5 | Routing: `exact_file_duplicate` / `duplicate_copy` / `same_edition_other_format` (stack) / `other_edition` / `translation` / `probable` | review §4.2; round 2 | |
| D6 | One review queue with keep-recommendation, reclaimable space, sort orders, sticky decisions; retire the overlapping dedup paths | review §4.3–4.4 | The keep-recommendation and space-saved view shipped in `f02f7cf` (`intel-content-dupes.html`). |
| M6 | Wire `/check-owned` into catalog results; FTS snippets (`ts_headline`) + UI for `/search/fulltext` | review §2 | Backends exist. |
| K10 | Reader memory: the full reader downloads the whole PDF (pdf.js) and epub.js loads the whole EPUB, which can crash mobile browsers on large illustrated books. Offer the quick page-image mode (`?quick=1`, `f02f7cf`) as a user choice in the library and default to it above a size threshold | honest-status #3; fides | |

## P2 — Valuable, sequenced after P0/P1

| ID | Item | Source | Notes |
|----|------|--------|-------|
| M8 | Multi-user for a trusted group: `user_library` membership over one canonical book, shared compounding metadata, trust rule D with an admin queue, non-admin `/override` routed through the queue | owner decision 3; round 2 | Requires K1 and K6. |
| AI0 | One `ai.complete(intent, …)` for all LLM call sites | ai-in-app | Prerequisite for AI1–AI7 (owner chose in-app routing). |
| AI1–AI7 | In-app router, single Postgres ledger with per-intent budgets, local-first, cloud opt-in per intent | ai-in-app; owner decision 2 | Measure local throughput before making goldmine local-only. |
| B5/M3 | Goldmine intelligence page = self-generated summary; stored with model, date and prompt version; refresh offered after ~6 months | owner decision 4 | Migrate existing `extra_metadata->'summary'`. |
| C2 | Offline reference-DB registry with disk budgets (OL works 4.1 GB, DNB; LibGen/AA metadata, owner-approved) | review §4.14 | Wikidata off by default; Google Books API-only. |
| C4 | Multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`, already configured) | review §4.15 | Also the translation signal for D5. |
| C1 | Editions / formats / languages grouping, using OL `work_key` | library-vision | With D5. |
| D2 | Cover perceptual hashing + backfill | dedup-overhaul | Comes in with L1 (`cover_phash`). |
| D7 | Dedup coverage guarantee + audit metric | dedup-overhaul | |
| A3 | Summary-aware quality score | library-vision | |
| M4 | Per-book enrichment explanation (sources, match keys, merge decisions) | v2-req R2.11.5 | LoC part done. |
| M7 | Bulk editor beyond tags (author/publisher/status) + UI; cover normalization and resize on ingest | review §2 | Tag endpoints exist. |
| M9 | Book DNA / wrap-up cards | v2-req R2.4 | After M2 (reads `reading_log`, `finished_at`). |
| K11 | One file-naming scheme: `organize_after_enrichment` (Genre/Author/Title tree) and `rename_book_file` (`Author - Title [ISBN].ext`) both run after enrichment | fides session | Pick one. Keep the unresolved-title guard and K6's hash capture. |
| K12 | Make the fides deployment reproducible: the SMTP relay depends on a host systemd SSH tunnel (`brainycat-smtp-tunnel.service`) and Readarr runs via ad-hoc `docker run` on the `arr` network. Document both in the runbook or move them into compose | fides ops | Neither is in the repo today. |
| K13 | "Get a book" (Readarr) returns nothing: Prowlarr has no book-capable indexer (The Pirate Bay is rejected by Readarr's validation) | fides ops | Add an ebook/audiobook indexer; configuration, not code. |
| K14 | Measure `sentence_match` (Google Books) hit rate on the saved 400 known / 100 unknown pools; try the stricter sentence picker | review §8 | Principle 4: evaluate before committing. |
| K15 | Lint/type debt to zero, then enforce in CI: 78 ruff findings and 25 unformatted files on `main`, plus mypy-strict pre-existing errors | ruff baseline; CLAUDE.md | K4 first. |
| C5 | Complete the 7 recommendation categories | library-vision | |

## P3 — Parked

| ID | Item | Source | Notes |
|----|------|--------|-------|
| K16 | ebook-convert-rs: HTML entities not decoded; double-encoded UTF-8 (`COPYRIGHT Â©`) | known-issues.md | Converter is a secondary path (Calibre fallback). Audit where bytes are decoded. |
| K17 | Split `routes/books.py` (1,887 lines; the honest-status target was 1,483) | honest-status #1 | Pure refactor; do after K15 so the diff stays reviewable. |
| K18 | Migrate the ad-hoc runtime `CREATE TABLE`s (47+) into Alembic | honest-status #2; CLAUDE.md | Follows the M12 schema audit. |
| K19 | Wire-or-delete audit for dead code found by the docstring pass: `sources/isbndb.py` (not dispatched), `social.unfollow_user`, `lending.list_my_requests`, `notifications.py` (no callers), and routes with no UI caller (reader bookmarks/annotations/sync-map, word-wise/X-Ray, status) | docstring pass | Some are wired by M6/M7/M2 UI work. |
| K20 | OCR result size: test the optimizer on large scans | honest-status #6 | |
| K21 | `/intelligence/quality` returns one row per file, so multi-format books appear once per format | fides | Group by book. |
| M5 | Word Wise / X-Ray reader overlay (backends exist) | review §2 | Needs Intello / AI0. |
| M6-s | Readwise export | Ideas Parking Lot | |
| — | Suffix-array / substring dedup | roadmap v3.0 | After D4. |
| — | KOReader kosync queue RFE | `docs/koreader-rfe-kosync-queue.md` | |
| — | Recipe / citation / RPG-sourcebook extraction | v2-req R2.11.9/10/12 | |
| — | Comics/manga reader modes | roadmap v1.1 #17/#20 | |
| — | Federation, book clubs, activity feed | roadmap v2.1 | |
| — | Prowlarr integration | v2-req R2.8 | See K13 for the Readarr side. |
| — | PDF reflow; MARC Z39.50; flashcards/quizzes | roadmap v3.0 | |
| — | Cross-project MCP / SSO / unified backup | v2-req R2.11.22/23/24 | |
| — | E-ink mode; offline PWA; Kindle-friendly UI | Ideas Parking Lot | |

## Deferred

| ID | Item | Reason |
|----|------|--------|
| M11 | Public GHCR images + Prometheus metrics | Owner decision 6: after the UI redesign and multi-user hardening (K1, M8). |

## Done (recent)

| Item | Where |
|------|-------|
| LoC removed from enrichment (0% hit rate) | `9df101f` |
| `original_filename` / `book_originals` phantom schema | PR #1 |
| Whitespace-only PDF/EPUB/audio metadata no longer produces empty titles | `f02f7cf` (`extract._blank_to_none`) |
| `google_books` quota backoff attributes | `f02f7cf` |
| Series suggestions no longer list duplicates as series (829 → 249) | `f02f7cf` |
| `fast_local` tolerates non-object `extra_metadata` | `f02f7cf` |
| 30-day retention for `enrichment_log` / `job_logs`; container log rotation | `f02f7cf` |
| Local Open Library lookup (56.7 M editions / 46.7 M ISBNs) wired into `fast_local` / `ol_works` | `f02f7cf` (reconcile in L2) |
| Docstrings (purpose + callers) on all 1,104 functions | `f02f7cf` |

## Known-issue coverage

Every known issue on record, and the item that addresses it.

| Known issue | Source | Backlog item |
|---|---|---|
| ebook-convert-rs: HTML entities not decoded | known-issues.md | K16 |
| ebook-convert-rs: double-encoded UTF-8 | known-issues.md | K16 |
| `original_filename` / `book_originals` phantom schema | known-issues.md | Done (PR #1); class covered by M12 audit |
| Scheduler loops importing modules absent from `main` (incl. `incipit_match`) | known-issues.md; fides logs | L1, L3, L4 |
| `extra_metadata` degrading from object to array | known-issues.md | M1 (CHECK), K3 |
| `routes/books.py` too large | honest-status #1 | K17 |
| Schema mostly created ad hoc, few migrations | honest-status #2; CLAUDE.md | M12 (audit), K18 |
| epub.js loads whole book into memory | honest-status #3 | K10 |
| Intello is a single point of failure | honest-status #4 | M10, AI0–AI7 (local-first) |
| No multi-user data isolation | honest-status #5 | M8 (after K1) |
| OCR results can be large | honest-status #6 | K20 |
| Test coverage ~21% vs `--cov-fail-under=80` | honest-status #7; CLAUDE.md | M12, K15 |
| `X-Auth-User` trusted as-is; `ecb_auth` signature not verified | CLAUDE.md | **K1** |
| Loops swallow exceptions and can no-op forever | CLAUDE.md | M10 |
| mypy strict pre-existing errors | CLAUDE.md | K15 |
| Overlapping dedup modules | CLAUDE.md; review §4.4 | D6 (retire paths) |
| Reading status/log routes fail (schema never migrated) | review §2 | M2 |
| Calibre `detect_calibre_library` ImportError; two test files don't collect | review §3.5 | M12 |
| `find_duplicates_by_content` has no cursor / fingerprint loop re-scans | review §3.4 | D1, L3 |
| CPU-bound work blocks the event loop | review §4.7 | K5 |
| Hashes of stored (modified) files don't identify originals | round 2 | K6 |
| Translation backends advertised but not implemented | review §3.7 | K8 |
| `books_series.series_index` insert fails | fides logs | K2 |
| Duplicate route definitions in `routes/admin.py` (F811) | ruff | K4 |
| Unimportable files stay in `incoming` silently | fides | K7 |
| Corrupt PDFs re-parsed every pass (MuPDF log flood) | fides logs | K9 |
| Two file-naming systems | fides session | K11 |
| SMTP tunnel and Readarr outside the repo | fides ops | K12 |
| Readarr has no book-capable indexer | fides ops | K13 |
| Dead code / routes without callers | docstring pass | K19 |
| Quality list repeats multi-format books | fides | K21 |
| Lint/format debt (78 findings, 25 files) | ruff baseline | K15 |
