# Tasks — Book Identification & Consistent Metadata

Dependency-first. Each task states the requirements it satisfies and how it is verified.
Conventions: `docs/steering/engineering.md`. Do not start until `requirements.md` is approved.
Gates per task: `make lint`, `make typecheck`, filtered `pytest`.

## T1 — Golden set and baseline harness `[R15]`
- `tests/fixtures/golden/` with `manifest.yaml` (file, expected identifiers, title, authors, language) and a
  runner that executes the current pipeline and prints precision / rate / coverage.
- Verify: runner produces a baseline report on today's code; committed as `docs/specs/book-identification/baseline.md`.
- Why first: every later task is judged against this number.

## T2 — Identifier normalization and typed storage `[R1, R2]`
- Pure module `identifiers.py`: `normalize_isbn`, `classify`, checksum, dash handling (reuse `isbn.py` logic; don't duplicate).
- Alembic migration: `book_identifiers(book_id, type, value, source, verified, created_at, UNIQUE(type,value,book_id))`;
  backfill from `books.isbn` + `extra_metadata` using only checksum-valid values; log rejected ones.
- Verify: unit tests (valid/invalid/ISBN-10/unicode dashes); migration up/down on a copy; backfill report lists counts changed/rejected.
- Data change: rewrites identifiers from existing rows — backup first, report rejected values.

## T3 — Single write path with provenance `[R7, R8, R9, R11, R13]`
- Migration: `field_provenance(book_id, field, source, source_rank, confidence, fetched_at, locked)`.
- `metadata_apply.apply()` enforces rank + lock rules, normalizes (T5 hooks), writes `metadata_history`, recomputes quality.
- Fix `metadata_audit.rollback_field` to use the allowlist + `apply`.
- Verify: unit tests for rank/lock/idempotence; a guard test that fails on `UPDATE books SET` for descriptive fields outside the module (allowlist for cover/embedding/search_vector).

## T4 — Source authority table and field merge `[R6, R12]`
- `SOURCE_AUTHORITY` config (one place), pure `choose(field, candidates)` implementing standards §4.
- Replace shortest/longest logic in `metadata.enrich_book`; ratings stored per source.
- Relevance guard extended: identifier conflict discards; identical-payload quarantine.
- Verify: unit tests per field incl. ties and conflicting identifiers; T1 harness shows no regression.

## T5 — Normalization standards `[R10]`
- Language → ISO 639-3; title/subtitle split and cruft strip; `author_sort`; publisher alias table; pubdate precision
  (migration adds `pubdate_precision`).
- Verify: table-driven unit tests from real examples in the library; migration reports rows changed.

## T6 — Identification ladder and review queue `[R3, R4, R5]`
- `identify.py` returns ranked Candidates using existing extractors (`isbn`, `title_confidence`, `sentence_match`, `deep_enrich`);
  auto-apply per R4 through `apply()`; `possible` lands in a queue surfaced in the Ops page.
- LLM path restricted to producing a query; result must be confirmed by a structured source.
- Verify: T1 harness meets R15 precision gate; test proving an unconfirmed LLM result is never written.

## T7 — Consolidate enrichment modules `[R9]`
- Fold `aggregator`, `deep_enrich`, `intelligence` (metadata parts) onto T3/T4/T6; delete superseded paths after tests pass.
  Flag, don't silently delete, anything with external callers.
- Verify: guard test green; all routes/MCP tools using them still pass their tests.

## T8 — Identifier-first dedup and format stacking `[R14]`
- `dedup_engine` / `format_stack` / `smart_merge` match on ISBN-13 first, fingerprint to verify; different editions linked not merged.
- Verify: unit tests (same ISBN two formats → one entry; different ISBN same title → linked); T1 harness dedup cases.

## T9 — Dry-run bulk re-identification `[R11, R16]`
- Admin endpoint/CLI: run T6 over the library with `dry_run=true`, output per-field intended changes and counts; apply only on confirm.
- Verify: on a backup copy, second real run yields 0 changes; dry-run output matches applied diff.

## T10 — CI gate `[R15]`
- GitHub Actions: lint, typecheck, unit tests, golden-set precision check (fails below R15 bar).
- Verify: workflow green on a branch; deliberately degrading the merge logic turns it red.

## Suggested order
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 (T10 can move up right after T1).

## T11 — Easy, reliable send-to-Kindle (separate track, not gated on R15)
Existing: `convert.send_to_kindle` + `POST /books/{id}/send-to-kindle` + per-user `kindle_email`. Gaps found in code:
- SMTP is unauthenticated, no STARTTLS/login, `From: brainycat@<smtp_host>`. Amazon only accepts mail from addresses on the user's
  Approved Personal Document E-mail List, and rejects/spams unauthenticated relays — needs real SMTP credentials + a sender address.
- Falls back to sending *any* file (MOBI/AZW3 are rejected by Amazon); accepted: EPUB, PDF, DOCX. No 50 MB check. File read fully into memory.
- `auto_send_kindle` is stored but nothing consumes it. New UI (`static/index.html`) has no Send button (only `index.old.html`).
- Untested end-to-end (`honest-status.md`).
Proposed: `SMTP_USER/PASSWORD/FROM/STARTTLS` settings; settings page shows "add <from> to your Approved list" with a Test button;
convert to EPUB before sending when needed; enforce size/format; button on book modal + bulk; honour `auto_send_kindle` on import.
Optional inbound: email a book to a BrainyCat address → import (reuses `email_consume`).
Verify: unit tests with a mocked SMTP (format/size selection, error mapping); one manual real send to a Kindle.
