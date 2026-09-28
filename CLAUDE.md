# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BrainyCat — self-hosted personal library for ebooks and audiobooks: ingest, identify, enrich
metadata (32 sources), read in-browser (EPUB/PDF/MOBI), sync (OPDS, KOReader, Kobo, ABS), and
manage via a Python/FastAPI backend with a vanilla HTML/JS frontend. Python 3.12, FastAPI, asyncpg,
PostgreSQL 16 (pg_trgm, pgvector), Docker, AGPL-3.0. See `README.md` for the full feature list.

Current focus: **book identification and one consistent metadata write path** (the enrichment
pipeline has ~25 modules independently writing `books` with no shared authority/provenance model).
Spec: `docs/specs/book-identification/` (requirements → tasks, traced by `[R#]`). Standards:
`docs/steering/metadata-standards.md`. Engineering conventions: `docs/steering/engineering.md`.
`docs/honest-status.md` is the actually-current feature/coverage status — trust it over `README.md`'s
feature list for what's *working* today, and update it when that changes. `docs/known-issues.md`
tracks engineering-level bugs (not new features — those go in `docs/roadmap.md`) that are found but
not yet fixed; check it before re-investigating something that might already be diagnosed there.

## Commands

```bash
ruff check brainycat/ tests/ && ruff format --check brainycat/ tests/  # make lint
mypy brainycat/                                                        # make typecheck
pytest tests/                                                          # make test — unit tests, no network
pytest tests/unit/test_isbn.py -q --no-cov                             # single file, skip the coverage gate
pytest tests/unit/test_isbn.py::test_clean_isbn13 -q --no-cov          # single test
alembic upgrade head                                                   # make migrate
uvicorn brainycat.web:app --reload --host 0.0.0.0 --port 8000          # make dev
docker compose -f docker-compose.standalone.yml up -d                  # full stack incl. Postgres
```

- `pyproject.toml` sets `--cov-fail-under=80` as a **default** pytest option, but actual coverage is
  ~21% (`docs/honest-status.md`) — a bare `pytest tests/` on a subset of files fails on the coverage
  gate even when every test passes. Add `--no-cov` when running anything less than the full suite.
- `tests/unit/` is pure/mocked, no DB or network, and is what CI-equivalent linting actually exercises.
  `tests/integration/test_live.py` hits a **running instance** at `https://localhost:8000`;
  `tests/integration/test_real_files.py` needs the fixture files under `tests/fixtures/` (auto-skips
  if absent); `tests/e2e/` needs a running instance and a browser. None of these are wired into the
  `Makefile` — `docs/roadmap.md` documents aspirational `make test-int`/`make test-e2e` targets that
  don't exist yet; run the files directly with `pytest tests/integration/... --no-cov` instead.
- `mypy` is `strict = true`; expect pre-existing errors in `config.py` (pydantic-settings `**kwargs`
  typing) and `db.py` (asyncpg's untyped `Record`) unrelated to most changes — check only the file(s)
  you touched, not the whole-tree error count.
- Migrations: 5 Alembic files under `migrations/versions/` against 47+ `CREATE TABLE` statements
  spread across the codebase — much of the schema is still created ad hoc rather than migrated.
  New schema changes must go through Alembic; don't add another runtime `CREATE TABLE`.

## Architecture

- **`brainycat/web.py`** wires the app: lifespan starts the DB pool, seeds default users, and starts
  the background scheduler; routers are mounted from `brainycat/routes/*.py`, each a thin FastAPI
  router (auth, books, catalog, enrichment, media, social, reader, admin, ai, kosync, ws, kobo,
  oauth, health, webdav, wanted, abs). Business logic lives in top-level `brainycat/*.py` modules —
  routes should stay thin (validate, call a module, return).
- **Auth (`brainycat/auth.py`)** resolves the current user through four methods, tried in order:
  (1) `X-Auth-User` request header — trusted as-is, meant to be set by a reverse proxy's forward-auth
  step (e.g. Caddy), auto-creates the user if unknown, `admin` role for username `ecb`; (2) an
  `ecb_auth` cookie (`username:timestamp:signature`) — parsed but the signature is **not verified**;
  (3) `Authorization: Bearer <token>` API key (used by the MCP server and external integrations),
  hashed and looked up in `api_keys`; (4) the app's own signed session cookie. Anything relying on
  (1) or (2) for real authorization needs a trusted proxy in front of it — neither is safe exposed
  directly.
- **Metadata enrichment** (`brainycat/metadata.py`, `aggregator.py`, `isbn.py`, `deep_enrich.py`,
  `intelligence.py`, `sources/*.py` — 32 external sources) is the largest and most fragmented part of
  the codebase: many modules issue their own `UPDATE books SET ...` with source-agnostic merge rules
  (e.g. "shortest title wins"). `brainycat/identify.py` is the new, pure (no DB/network) grading
  module for ISBN identification — `resolve()`/`decide()` grade multi-source evidence into confidence
  classes (`certain`/`probable`/`possible`) before anything is auto-applied; see
  `docs/steering/metadata-standards.md` for the target write-path/provenance model this is moving
  towards, and `docs/specs/book-identification/baseline.md` for measured precision/coverage numbers
  from the full production library.
- **`brainycat/scheduler.py`** runs supervised background loops (enrichment, format-stacking, OCR
  submission, FTS indexing, etc.) with row-locking and crash recovery. Loops catch their own
  exceptions liberally (`except: pass`) so a broken loop doesn't take down the others — but this also
  means a loop can silently no-op forever; when debugging "a background feature does nothing", check
  for a swallowed exception before assuming the feature never ran (this has happened: `format_stack.py`
  imported a function from `fingerprints.py` that didn't exist, for as long as the loop existed).
- **Content fingerprinting / dedup** (`brainycat/fingerprints.py`, `dedup_engine.py`, `format_stack.py`,
  `smart_merge.py`, `edition_diff.py`) has several overlapping, not-fully-consolidated approaches to
  the same problem (duplicate detection across formats, edition diffing). `fingerprints.py`'s k-gram
  hashing must use a fixed hash (`zlib.crc32`), not Python's builtin `hash()` — the latter is
  randomized per process (`PYTHONHASHSEED`), so fingerprints computed before/after a restart would
  silently stop matching.
- **Format conversion**: EPUB ↔ PDF ↔ MOBI via `ebook-convert-rs` (Rust) → Calibre → WeasyPrint
  fallback chain (`format_convert.py`, `pdf_convert.py`, `conversion.py`); Calibre is a ~500MB Docker
  dependency used as a fallback, not the primary path.
- **Readers**: `static/reader.html` (EPUB via epub.js, PDF via pdf.js) and `brainycat/routes/reader.py`
  handle in-browser reading, progress sync, annotations, and OPDS; MOBI/AZW3 auto-convert to EPUB on
  first open.
- **`brainycat/mcp_server.py`** exposes ~28 tools over MCP for AI-assistant integration (search,
  enrich, convert, recommend, etc.), authenticating via the Bearer API key path in `auth.py`.
- **`extra_metadata` JSONB** on `books` is the intentional escape hatch for fields that don't have a
  dedicated column yet (GIN-indexed) — prefer it over a new migration for provisional/low-confidence
  data (e.g. queued-but-unconfirmed identification candidates), but a proper table/column is still the
  right answer once a field is load-bearing.

## Conventions

- Dynamic SQL column names (e.g. building an `UPDATE ... SET` from a partial-update request body) must
  come from a module-level allowlist, never straight from request data.
- A background job or enrichment step that swallowed its own exception must not report success.
- Commit prefixes actually used in this repo's history (by frequency): `feat:`, `fix:`, `docs:`,
  `refactor:`, `perf:`, `ui:`, `test:`, `chore:`.
