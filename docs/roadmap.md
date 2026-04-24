# BrainyCat Roadmap

*Born: Tuesday 2026-04-22. Feeling very adult by Friday.*

## Completed ✅

### Core (Day 1-2)
- [x] FastAPI backend with 230+ routes
- [x] PostgreSQL with pgvector + pg_trgm
- [x] 22 upload formats (EPUB, PDF, MOBI, AZW3, KFX, FB2, DOCX, ODT, TXT, RTF, HTML, MD, DJVU, CBZ, CBR + audio)
- [x] Docker deployment with hot reload (rsync + restart)
- [x] Multi-user auth with session cookies
- [x] Shared HTTP client with connection pooling (73 call sites)

### Enrichment (Day 1-3)
- [x] 32 metadata sources with parallel fetching
- [x] Adaptive rate limiting (fail2ban-style escalation)
- [x] Calibre-style merge (shortest title, longest description, averaged ratings)
- [x] Smart ISBN routing (French → BnF first, German → DNB)
- [x] Cover validation (MD5 check against Google Books dummy images)
- [x] Post-enrichment writeback into EPUB + cover regeneration

### ISBN Intelligence (Day 2-3)
- [x] 6 extraction methods (OPF, full-text, barcode/pyzbar, filename, title, check-digit completion)
- [x] Multi-ISBN storage with type detection (print, ebook, PDF, audiobook)
- [x] Unicode dash handling (U+2010–U+2014)
- [x] 285 registration groups from official ISBN Range Message
- [x] Full-text extraction (no page limit — regex on 1MB text is <50ms)
- [x] BISAC/Thema subject code mapping + LLM verification via Groq

### Reading (Day 3)
- [x] EPUB reader (epub.js, scrolled-doc, themes, font selector, OpenDyslexic)
- [x] PDF reader (pdf.js, lazy rendering, in-app viewing)
- [x] MOBI/AZW3 auto-convert to EPUB on first open
- [x] Stylus annotations (pressure-sensitive pen/highlighter, per-page, synced)
- [x] Dictionary (language-aware, tries book language first)
- [x] Clippings (save/explain/translate, Markdown export for Obsidian)
- [x] Custom CSS injection
- [x] Reading progress save/restore (was broken — POST vs PUT fix)
- [x] Reading goals ("50 books in 2026")

### Discovery (Day 3)
- [x] 15 free catalog sources (Gutenberg, Standard Ebooks, LibriVox, Internet Archive, Feedbooks, OAPEN, arXiv, Semantic Scholar, CORE, Unpaywall, DOAB, Loyal Books, ManyBooks, GitHub, OpenStax)
- [x] 8 pre-configured OPDS subscriptions (75,000+ free books)
- [x] One-click import from any catalog to library (server-side download)
- [x] Taste engine (7-category Book Genome)

### Infrastructure (Day 3)
- [x] web.py split: 3,776 → 139 lines (9 APIRouter modules)
- [x] Supervised scheduler (crash recovery, row locking, timeouts)
- [x] SELECT FOR UPDATE SKIP LOCKED on all background loops
- [x] Timeouts on all external calls (15s per source, 30s per book, 120s OCR)
- [x] Connection pool config (min=3, max=20, 30s statement timeout)
- [x] Backup endpoint (asyncpg COPY → gzipped CSV)
- [x] GIN index on extra_metadata JSONB
- [x] OCR pipeline with PDF chunking for large files
- [x] First-run setup wizard
- [x] Auto-generated secret key
- [x] docker-compose.standalone.yml (zero-config with PostgreSQL)

### Intello Integration (Day 3)
- [x] TTS engine: orpheus → groq (was silently falling back to Piper)
- [x] Voice endpoint: /api/v1/tts/voices (was 404)
- [x] OCR download: /api/v1/ocr/jobs/{id}/result (was using raw file path)
- [x] OCR output: hybrid mode (100x smaller than searchable_pdf)
- [x] LLM endpoint: /v1/chat/completions (OpenAI-compatible)
- [x] task_hint on all LLM calls (analysis/creative/classification/translation)
- [x] HTTP timeout: 120s (deep mode needs 60s+)
- [x] Voxtral voice for French TTS
- [x] async_mode for long TTS chunks
- [x] Language codes: ISO 639-2 (3-letter: eng, fra, deu)

### Data Quality (Day 3)
- [x] 535 garbage ISBNs cleaned (UUIDs/URNs stored as ISBN)
- [x] 26 duplicates confirmed and merged
- [x] 288 editions detected (multilingual)
- [x] 704 pubdates filled from copyright_year
- [x] 295+ word/page counts
- [x] 63 BISAC subject codes mapped
- [x] Audiobook chapter merge (19 MP3s → 1 M4B, 46% smaller)

## In Progress 🔄

- [ ] ISBN re-extraction (recovering from garbage cleanup, 80% → target 95%)
- [ ] Genre classification (4.9%, enrichment loop running)
- [ ] OCR pipeline (30 complete, Intello improving)
- [ ] Enrichment backlog (3 books/minute, all rate limiters green)
- [ ] Fingerprinting (391 done, 1,100 pending)

## TODO 📋

### High Priority
- [ ] Screenshots for r/selfhosted launch (library grid, book detail, reader)
- [ ] books.py split (1,483 lines — next god file)
- [ ] Series auto-detection from title patterns ("Book 1", "Vol. 2", "Tome 3")
- [ ] Batch LLM genre classification (jump tags from 5% to 60%+)
- [ ] Open Library metadata contribution (push enriched data back)

### Medium Priority
- [ ] Virtual libraries (saved filter presets)
- [ ] Hierarchical tag browser (Genre.Fiction.SciFi)
- [ ] Book DNA / Spotify Wrapped for books (shareable reading stats card)
- [ ] Action chains (import → enrich → convert → send automation)
- [ ] File watcher for auto-import (Samba/NFS drop folder)
- [ ] WebSocket for real-time library updates
- [ ] Multi-user data isolation (per-user visibility)

### Nice to Have
- [ ] Recipe extraction from cookbook PDFs
- [ ] Comic/manga metadata from ComicVine
- [ ] Children's book age ratings (Lexile/AR)
- [ ] Sheet music metadata from MusicBrainz
- [ ] Publisher analytics (aggregate reading trends)
- [ ] Alembic migration coverage (currently 2 migrations for 33+ tables)
- [ ] mypy enforcement
- [ ] Test coverage improvement (182 tests, needs DB fixtures)

## Ideas Backlog 💡

### Reading Experience
- [ ] **Book status enum** — Want to Read / Currently Reading / Finished / Library Only. Enables "TBR pile" view, finished count for goals, and "currently reading" shelf. Simple `status` column on books table + filter in UI.
- [ ] **Daily reading logs** — "I read 30 pages of X today." Track page counts per day per book. Enables: reading speed trends, streak calculation, "you read 2.5 hours this week" stats. Table: `reading_logs(user_id, book_id, date, pages, minutes)`.
- [ ] **Monthly/yearly wrap-up card** — Spotify Wrapped for books. Shareable image: "In 2026 I read 47 books, 60% fiction, favorite author was Ursula Le Guin, longest streak 14 days, 312 hours total." Generate as SVG → PNG. All data already exists in reading_progress + books_tags + books_authors.
- [ ] **Reading speed trends** — pages/hour over time, by genre, by time of day. Requires daily reading logs.
- [ ] **"Currently reading" widget** — small card showing book cover + progress bar + ETA. Embeddable (iframe/SVG) for blogs, Notion, etc.

### Discovery & Social
- [ ] **"You already own this" check** — when browsing catalogs, cross-reference against library by ISBN/title. Prevents re-downloading.
- [ ] **Reading challenges** — "Read 5 books from a new genre", "Read a book from every continent", "Read 3 books over 500 pages." Gamification with badge SVGs.
- [ ] **Book DNA shareable card** — visual fingerprint of your reading taste. Radar chart: fiction/non-fiction, genres, languages, avg length, reading pace. Shareable URL or image.
- [ ] **Granular privacy controls** — per-book visibility (public/friends/private). Currently all-or-nothing.
- [ ] **Activity feed** — "Alice finished 'Dune', Bob started 'Neuromancer', Carol highlighted 3 passages in 'Sapiens'." Real-time via WebSocket.

### Intelligence
- [ ] **3-tier semantic memory** (Beever Atlas pattern) — Tier 2: passages/quotes extracted from books. Tier 1: chapter themes clustered from passages. Tier 0: book summary synthesized from themes. Pre-compiled, queryable, deterministic fallback if LLM fails.
- [ ] **Wiki-first book pages** — pre-generate structured intelligence pages per book: summary, themes, characters, key concepts, related books. Cache as HTML. LLM generates, regex validates completeness, deterministic splice fills gaps.
- [ ] **Character map / relationship graph** — extract named entities from fiction, build character relationship graph. "Who is related to whom in this 800-page epic?"
- [ ] **Cross-book knowledge graph** — connect concepts across books. "These 3 books all discuss stoicism." Requires entity extraction + clustering.
- [ ] **Recipe extraction** — detect cookbook PDFs, extract structured recipes (ingredients, steps, servings). Niche but passionate community.
- [ ] **Citation extraction** — for academic papers, extract references as BibTeX. Link cited papers to library if owned.

### Technical
- [ ] **FTS5 page-level indexing** (Grimoire pattern) — index book content at page/chapter level with snippet(). "Find the passage about X in chapter 3." Currently we have pgvector for semantic search but no full-text page-level index.
- [ ] **Scan-failed flag** (Grimoire pattern) — mark books that failed processing (OCR, extraction, conversion) so they're not retried forever. Currently we use `isbn_ocr_tried` in JSONB; should be a proper column.
- [ ] **File watcher** — inotify/watchdog on incoming folder. Auto-import books dropped via Samba/NFS. Debounce, ignore patterns, recursive.
- [ ] **WebSocket for library updates** — when enrichment completes or a book is uploaded, push update to all connected clients. No more manual refresh.
- [ ] **Contributor role on authors** — author vs editor vs translator vs illustrator vs narrator. Currently just names.
- [ ] **Open Library contribution** — push enriched metadata back (covers, descriptions, subjects). Opt-in, admin-controlled. Virtuous cycle.
- [ ] **Publisher analytics** — aggregate reading trends across community server users. Anonymized: "85% of readers who started your book finished it." Indie publishers would value this.
