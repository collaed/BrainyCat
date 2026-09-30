# BrainyCat — Onboarding

> Two audiences: **new users** getting a library running, and **new contributors** getting oriented
> in the codebase. Updated 2026-09-30 to include the owned-summaries flow (see
> [`roadmap/library-vision.md`](./roadmap/library-vision.md)).

## Part 1 — New user onboarding

### 5-minute path (standalone)
```bash
git clone https://github.com/collaed/BrainyCat.git
cd BrainyCat
cp .env.example .env
docker compose -f docker-compose.standalone.yml up -d
# → http://localhost:8000 → setup wizard creates your admin account
```
Includes PostgreSQL + pgvector. No external dependencies. The setup wizard (`/static/setup.html`)
creates the first password-set admin account (the passwordless placeholder admin used by the
`X-Auth-User` header path does not count as "set up").

### First 5 minutes — what you should see
1. Setup wizard → create admin → land on the library.
2. Drop an EPUB/PDF (or a `.zip` of several — each becomes its own book) onto the drop zone, or use
   the incoming folder (`BRAINYCAT_INCOMING_DIR`).
3. Enrichment starts in the background — covers, ISBNs, genres, descriptions fill in automatically.
4. Open a book → read in the browser with progress sync, themes, and a dictionary.

### Optional integrations
- **Intello (AI features):** set `BRAINYCAT_INTELLO_URL` → unlocks TTS, STT, OCR, summaries,
  Word Wise/X-Ray. Everything works without it; AI features degrade gracefully.
- **Existing PostgreSQL:** set `DATABASE_URL` and use `docker compose up -d`.
- **ABS mobile app:** point it at `yourserver:8000` for playback/browse/sync.
- **OPDS readers (Moon+, KOReader, Calibre):** add the OPDS feed URL.
- **Kindle delivery:** set the SMTP settings (`SMTP_HOST/PORT/USER/PASSWORD/FROM`) or a
  `RESEND_API_KEY`.

### Owned summaries — the "read the summary first" flow (planned; library-vision Phase B)
If you own book summaries (getAbstract, Blinkist, self-authored), BrainyCat will:
1. Detect them automatically from provider boilerplate when you drop them in incoming or upload them
   (or you can flag a file as a summary manually, with a provider dropdown).
2. Associate each summary with its full book by title/author.
3. On a full book that has a linked summary, offer **"Read the summary first"** (or "Listen (X min)"
   for audio) above "Open full book" — so you can skim the abstract and only invest in the full book
   if it earns it.
Summaries have no ISBN and are deliberately excluded from ISBN/title enrichment so they are never
"corrected" into nonsense.

### Recommended first-run settings
- Turn on the incoming-folder watcher if you drop files via Samba/NFS.
- Set your reading languages (fluent/secondary) so enrichment routing prefers the right regional
  source (French → BnF, German → DNB).
- Optionally enable offline reference DBs (`BRAINYCAT_OFFLINE_LOOKUP=true`) for fast, unlimited
  local ISBN/title lookup against the OpenLibrary dump (and BnF, auto-enabled if your library is
  >30% French). Google Books has no dump and stays API-only.

## Part 2 — New contributor onboarding

### Architecture in one paragraph
FastAPI + `asyncpg`, single process, ~16 supervised background asyncio loops. PostgreSQL 16
(pgvector, pg_trgm, unaccent). Vanilla HTML/JS frontend, **no build step**. Deploy via `docker cp`
into the running container then `docker restart` (code is not volume-mounted). See
[`devdocs/architecture.md`](../devdocs/architecture.md) and
[`devdocs/data-model.md`](../devdocs/data-model.md).

### Where things live
- `brainycat/web.py` — app wiring; `brainycat/routes/` — route modules.
- `brainycat/scheduler.py` — the supervised background loops.
- `brainycat/metadata.py` + `brainycat/sources/` — enrichment dispatch + 21 source adapters.
- `brainycat/isbn.py`, `brainycat/identify.py`, `brainycat/confidence.py` — identification.
- `brainycat/fingerprints.py` — content dedup (see `roadmap/dedup-overhaul.md` for the planned rework).
- `migrations/versions/` — Alembic migrations (current max: `011_translations`; next is `012`).

### Conventions (enforced)
- Additive, idempotent migrations (`IF NOT EXISTS`) with a working `downgrade()`.
- Thread-safe writes; parameterized SQL only (no string interpolation of values).
- Gate destructive/automated writes on per-book state columns (`identity_status`, and the planned
  `content_type`) — never let a pipeline clobber a manually-corrected or non-book item.
- Graceful degradation without Intello — AI features hide/fallback, they never hard-fail.
- **Do not enable `ruff`'s `TCH` rule** — it moves Pydantic body-model imports into
  `if TYPE_CHECKING:`, which FastAPI needs at runtime (documented in `pyproject.toml`).
- No `books.original_filename` / `book_originals` — those never existed; use `book_files.file_name`
  (see `docs/known-issues.md`).

### Run the tests
```bash
python3 -m pytest tests/unit/ -q
```
Note: two pre-existing test modules (`test_calibre.py`, `test_epub_check.py`) currently fail to
collect due to missing `calibre_import` symbols — this is tracked as Task M12 in
`roadmap/master-improvement-plan.md`, not something you introduced.

### Reading the roadmap before you build
Start with [`roadmap/master-improvement-plan.md`](./roadmap/master-improvement-plan.md) (umbrella),
then the relevant detailed plan ([`library-vision.md`](./roadmap/library-vision.md) or
[`dedup-overhaul.md`](./roadmap/dedup-overhaul.md)), then the prioritized [`backlog.md`](./backlog.md).
