# BrainyCat — Honest Status

*Last updated: Friday 2026-04-24*

## What Works

| Feature | Status | Notes |
|---|---|---|
| Upload & store books | ✅ Solid | 22 formats, atomic writes |
| Metadata enrichment | ✅ Running | 32 sources, 3 books/min, adaptive rate limiting |
| EPUB reader | ✅ Works | Smooth scroll, themes, fonts, dictionary, progress |
| PDF reader | ✅ Works | In-app pdf.js, lazy rendering, progress tracking |
| MOBI reading | ✅ Works | Auto-converts to EPUB on first open |
| Stylus annotations | ✅ New | Pressure-sensitive, pen + highlighter, synced |
| ISBN extraction | ✅ Strong | 6 methods including barcode scanning |
| Cover generation | ✅ Works | 99.9% coverage |
| Background enrichment | ✅ Running | Supervised, row-locked, crash-recoverable |
| OCR pipeline | ✅ Running | 30 complete, auto-submits, splits large PDFs |
| Duplicate detection | ✅ Works | 26 confirmed, 66 dismissed, pg_trgm |
| Free catalog browsing | ✅ Works | 15 sources, one-click import |
| OPDS subscriptions | ✅ Works | 8 pre-configured, 75K+ free books |
| Docker deployment | ✅ Works | Standalone with PostgreSQL included |
| First-run setup | ✅ Works | Wizard creates admin account |
| Backup | ✅ Works | 6.3MB gzipped CSV for 1,528 books |
| MCP server | ✅ Works | 28 tools for Claude/GPT integration |
| ABS mobile compat | ⚠️ Basic | Login, browse, play work; edge cases untested |
| Kindle delivery | ⚠️ Untested | SMTP configured but not verified end-to-end |
| Federated social | ⚠️ Stub | Profile hash + feed exist, cross-instance untested |

## What's Incomplete

| Feature | Coverage | Blocker |
|---|---|---|
| ISBN | 80% (recovering) | 535 garbage ISBNs cleaned, re-extraction running |
| Description | 61% | Enrichment running, will climb |
| Tags/genres | 5% | Google rate-limited, LLM classifier available |
| Pubdate | 46% | Filled from copyright_year, enrichment adding more |
| Series | 6% | Needs auto-detection from title patterns |
| BISAC codes | 4% | Mapped from tags, LLM fallback working |

## Known Issues

1. **books.py at 1,483 lines** — next split target
2. **Only 2 Alembic migrations** for 33+ tables — schema changes need care
3. **epub.js loads entire book into memory** — large illustrated EPUBs may crash mobile browsers
4. **Intello is a single point of failure** — all AI features degrade gracefully but 5 features go dark simultaneously
5. **No multi-user data isolation** — all users see all books (fine for family, not for strangers)
6. **OCR results can be large** — optimizer exists but needs more testing
7. **Test coverage at ~21%** — 182 tests exist but need DB fixtures for more

## Architecture Decisions

| Decision | Why | Trade-off |
|---|---|---|
| PostgreSQL (not SQLite) | pgvector for semantic search, pg_trgm for fuzzy match | Heavier to deploy |
| Vanilla HTML/JS (not React) | Simpler, no build step, fast iteration | Will get painful if UI grows much more |
| Python/FastAPI (not Node) | 3x more concise, better async, auto-generates OpenAPI | Smaller ecosystem than Express |
| Calibre as fallback converter | Handles 25+ formats with edge cases | Heavy dependency (500MB+ in Docker) |
| JSONB for extra_metadata | Flexible, no migrations needed | Junk drawer risk (mitigated by GIN index) |
