# BrainyCat — Release Notes

All significant changes since project inception, in reverse chronological order.

---

## v1.0.0 — "The Marathon" (April 29, 2026)

**60+ features in a single session.** Feature-complete for r/selfhosted launch.

### AI Intelligence (12 features)
- **Story Graph** — narrative arc visualization. LLM analyzes book in 10 segments, scores tension (0-10), identifies key events. SVG export, multi-book comparison overlay, AI story generation from premise + inspiration books.
- **Ask This Book** — RAG-style Q&A grounded in actual book content (first 4000 words as context).
- **Book Recap** — "Where was I?" LLM summary up to current reading position. Perfect for resuming abandoned books.
- **AI Mind Maps** — structured JSON concept maps (4-6 branches, 2-4 children) from book description.
- **Chapter Auto-Summaries** — bulleted notes per chapter via LLM (EPUB).
- **Book NLP / Characters** — extract characters (name, role, importance), themes, key quotes.
- **Auto-tag from Content** — LLM reads first pages, suggests genre + tags + audience + mood, auto-applies.
- **LLM OCR Post-Correction** — fixes garbled scanned text with 30-50% error reduction.
- **Vocabulary Difficulty Scoring** — CEFR level estimation (A1-C2) based on word frequency analysis.
- **Recommendations** — tag-based similarity + personalized (weighted by reading history, excludes read books).
- **Shareable Note Cards** — SVG images from highlights with book attribution and theming.
- **Similar Passages Finder** — full-text search across all annotations and clippings.

### Reading Experience (10 features)
- **RSVP Speed Reading** — Spritz-style word-at-a-time display at configurable WPM with optimal recognition point.
- **Bionic Reading** — bold first letter of each word (ADHD/dyslexia support), toggle in reader.
- **Reading Speed Test** — calibrate WPM, stored in preferences, used by time estimator.
- **Reading Time Estimator** — personalized "X hours to finish" based on actual pace from reading_log.
- **Reading Streaks** — current streak, longest streak, total days read.
- **Reading Goals** — "50 books in 2026" with progress tracking (books or minutes).
- **Reading Challenges** — personal goals with criteria and deadlines.
- **Book DNA / Wrapped** — Spotify Wrapped-style yearly reading summary.
- **Reading Heatmap** — GitHub-style contribution graph (daily sessions).
- **Book Status** — Want to Read / Reading / Finished / Abandoned with timestamps.

### Sync & Compatibility (9 protocols)
- **KOReader Sync** — full kosync protocol (position + annotation sync via JSONB).
- **Kobo Sync** — library listing + progress for Kobo e-readers (Bearer token auth).
- **WebDAV** — generic sync for any WebDAV reader (Basic auth, PROPFIND support).
- **OPDS-PS Page Streaming** — individual PDF pages as PNG at requested width.
- **ABS Mobile App** — expanded compat shim: /api/status, /api/ping, series, collections.
- **TTS Podcast Feed** — subscribe to audiobooks in any podcast app (RSS).
- **WebSocket** — real-time enrichment events pushed to connected clients.
- **MARC21 Export/Import** — standard library format (Koha, Evergreen, OpenBiblio compatible).
- **API Key Management** — view/regenerate for all sync integrations.

### Import & Export (7 features)
- **Goodreads/StoryGraph CSV** — reading history with shelf→status mapping, book matching.
- **Kindle Clippings** — My Clippings.txt parser with auto-matching to library books.
- **Calibre Library** — reads metadata.db SQLite directly (title, authors, tags, ISBN).
- **Import from URL** — paste link, server downloads and imports.
- **Camera ISBN Scanner** — phone camera barcode detection (BarcodeDetector API).
- **Obsidian Vault Export** — ZIP of Markdown files with blockquote highlights.
- **Annotated PDF Download** — serves PDF with user's highlights permanently embedded.

### Library Management (8 features)
- **Series Auto-Detection** — 5 regex patterns scan titles for "Book 1", "Vol. 2", "#3".
- **Smart Merge** — detect ISBN duplicates, consolidate files/annotations into one entry.
- **Book Timeline** — full event history (imported → enriched → read → annotated).
- **Book Comparison** — side-by-side metadata + shared tags.
- **PDF Page Extraction** — extract page range as new book (chapter extraction).
- **Activity Feed** — timeline of all library events (enrichments, imports, reads).
- **Book Lending Tracker** — who has my physical copy, mark as returned.
- **Collections** — user-created book groups beyond shelves.

### Authentication & UI (5 features)
- **OAuth/OIDC** — Google + generic OIDC (Keycloak, Authentik). Auto-creates user on first login.
- **Theme Toggle** — dark/light/auto, persisted in user preferences.
- **Public Catalog** — `/catalog` — clean, responsive, no-auth browsing page.
- **Clean Header** — two-row nav with live book count + OPDS link.
- **Readarr Integration** — search Readarr catalog from BrainyCat.

### Experimental Framework (10 evaluable features)
- TextProfileSignature (Apache Nutch fuzzy hash)
- MinHash LSH (datasketch corpus-scale dedup)
- Duplicate Page Detection (pixel hash per PDF page)
- eKitaab File Rename (Author - Title [ISBN].ext)
- Kindle EPUB Fix (extended: empty img, control chars, broken hrefs)
- Reading Heatmap (GitHub-style contribution graph)
- AI Mind Maps (structured concept maps)
- Shareable Note Cards (SVG export)
- PDF Annotation Embedding (write highlights into PDF)
- ISBN Lookup Evaluation (Open Library comparison)

### Infrastructure
- Consolidated health check (`GET /health` — DB, Intello, disk)
- WebSocket broadcast wired into enrichment loop
- `story_graphs` table, `reading_challenges` table, `book_loans` table, `clippings` table, `kosync_bookmarks` table, `kosync_progress` table, `reading_log` table, `reading_goals` table, `collections` table, `collection_books` table, `book_signatures` table

---

## v0.9.0 — "CWA-Inspired" (April 28, 2026)

Inspired by Calibre-Web-Automated feature set.

### New Features
- **EPUB Fixer on ingest** — UTF-8 declaration, language tag, stray img removal, NCX link fixes
- **Magic Shelves** — 12 dynamic views with live counts + UI sidebar
- **Auto-send to Kindle** — toggle in settings, emails after enrichment
- **Auto-writeback** — metadata written back into EPUB file after enrichment
- **File watcher** — polls /data/incoming every 10s, debounce, auto-import (Samba/NFS)
- **Full-text search** — PostgreSQL websearch_to_tsquery endpoint
- **PDF dark mode** — CSS filter (invert + hue-rotate) on canvas
- **In-book search** — searches all spine items client-side
- **Corruption check** — zero-filled, broken PDF, invalid EPUB rejected on upload
- **Pamphlet detection** — PDFs <10 pages + <256KB flagged
- **Intello unified lookup** — primary enrichment path (one call → all sources)
- **Google Books API key** — 100→1000/day quota
- **Robust LLM parsing** — 5-layer JSON fallback
- **Soft entity lifecycle** — confirmed vs pending for LLM-generated tags

### Enrichment Improvements
- Title variant search (strip dots, years, publisher prefixes)
- Two-step query (FOR UPDATE incompatible with aggregates → fixed)
- Disabled Amazon + LoC (0% hit rate, IP ban risk)
- Least-tried-first ordering with quality ASC tiebreaker

---

## v0.8.0 — "MCP & Taste" (April 21-27, 2026)

### Major Features
- **MCP Server** — 28 AI tools for Claude/GPT integration
- **Book Genome taste engine** — 7-category DNA (Author, Community, Hidden Gems, Series, Anti, NLP themes)
- **OPDS v2** — full catalog with search, pagination, covers
- **ABS mobile app compatibility** — login, browse, play, sync
- **Plugin system** — custom columns, virtual libraries
- **Federated social** — cross-instance following (3-layer privacy)
- **160 tests** (138 unit + 22 integration)

### Enrichment
- Multi-source aggregator with conflict resolution
- Amazon multi-country (12 regions)
- Goodreads CSV import
- EPUB linter (epubcheck integration)
- KFX input format support

---

## v0.7.0 — "Embeddings & AI" (April 18-20, 2026)

### Major Features
- **pgvector embeddings** — TF-IDF based, background generation
- **Similar books** — vector similarity search
- **AI companion** — chat with context from pgvector search
- **WebSocket activity feed** — real-time updates
- **Collaborative annotations** — shared highlights
- **53 tests** — scanner regex fix, ISBN regex fix

### Reader
- Bilingual reader (side-by-side translation)
- Sync maps (position mapping between formats)
- MOBI metadata extraction

---

## v0.6.0 — "Metadata Writeback" (April 15-17, 2026)

### Major Features
- **Metadata writeback** — enriched data written back into EPUB files
- **Efficiency dashboard** — source hit rates, cost tracking
- **Background writeback** — non-blocking, queued
- **Multilingual ISBN extraction** — 10 languages, EU legal compliance
- **Auto-detect series** from Google Books + Amazon during enrichment

### Sources
- 7 metadata providers (Google Books, Open Library, Gutendex, Amazon, LoC, Hardcover, OCLC)
- IPv6 preference for scraping
- Google→Amazon proxy strategy

---

## v0.5.0 — "Pro-Grade Dedup" (April 12-14, 2026)

### Major Features
- **Winnowing fingerprinting** — content-based cross-format dedup
- **Structural fingerprinting** — layout-aware comparison
- **OCLC Classify** — WorldCat subject headings
- **Thema codes** — international genre classification
- **LLM genre classification** — Groq Llama 3.3 70B
- **WeasyPrint EPUB→PDF** — proper HTML/CSS rendering
- **ISBN extraction** — OPF metadata + full-text scanning

### Enrichment
- Background enrichment scheduler (16 books/90s)
- Activity tracking per method
- Workbook flag detection

---

## v0.4.0 — "Catalog & Discovery" (April 9-11, 2026)

### Major Features
- **Gutenberg catalog** — search + one-click import
- **LibriVox catalog** — free audiobooks
- **Library of Congress** — metadata source
- **Hardcover** — social metadata source
- **Content fingerprinting** — background duplicate detection
- **Intel sub-pages** — source reliability, enrichment stats

---

## v0.3.0 — "Intello Delegation" (April 6-8, 2026)

### Architecture
- **Delegated OCR to Intello** — removed tesseract from image (-200MB)
- **Delegated TTS/STT to Intello** — removed Calibre dependency (-1.3GB image)
- **Content-based duplicates** — hash comparison
- **PDF covers** — first-page rendering
- **STT chapter split** — audio → text → chapters

---

## v0.2.0 — "Search & Batch" (April 3-5, 2026)

### Features
- **List view** — sortable headers, infinite scroll
- **Multi-signal duplicate detection** — title + ISBN + fingerprint
- **Batch actions** — multi-select delete, tag, enrich
- **OCR** — page-by-page processing
- **PDF covers** — auto-generated from first page
- **Cover download** — fetch from external sources

### Fixes
- Search pagination (was broken — API limit 200, JS sent 500)
- Deleted 427 garbage path-titled books (freed 9.2GB)
- Author dedup ('First Last' ↔ 'Last, First')

---

## v0.1.0 — "Genesis" (April 1, 2026)

### Initial Release
- Unified ebook/audiobook library
- Upload EPUB, PDF, MOBI, MP3, M4B
- Basic metadata extraction from files
- PostgreSQL storage with full-text search
- Docker deployment
- Web UI with grid view
- Series detection from metadata
- Basic enrichment (Open Library)

---

## Architecture Decisions (Historical)

| Date | Decision | Rationale |
|---|---|---|
| Apr 1 | Python/FastAPI + PostgreSQL | Rapid development, asyncpg performance |
| Apr 6 | Delegate heavy processing to Intello | Keep BrainyCat image small (<500MB) |
| Apr 7 | Remove Calibre dependency | -1.3GB image, ebook-convert-rs as replacement |
| Apr 12 | Winnowing over simple hashing | Cross-format dedup (EPUB vs PDF of same book) |
| Apr 15 | pgvector for embeddings | Similar books without external vector DB |
| Apr 18 | WebSocket for real-time | Activity feed without polling |
| Apr 21 | MCP server (28 tools) | AI assistant integration (Claude, GPT) |
| Apr 28 | Intello unified lookup | One call → all sources in parallel |
| Apr 29 | Experimental framework | Evaluate algorithms side-by-side before committing |
| Apr 29 | Story Graph | Bridge reading tool → writing tool |

---

## Stats at Launch

- **1,718 books** in production library
- **7,689 lines** of route code (14 route files)
- **24 Python modules** created in final session alone
- **160 tests** (unit + integration)
- **32 metadata sources** with intelligent routing
- **9 sync protocols** (OPDS, KOReader, Kobo, WebDAV, ABS, MCP, WebSocket, Podcast, OPDS-PS)
- **12 AI features** powered by Intello (Groq Llama 3.3 70B)
- **10 experimental features** with evaluation framework
- **Docker image** < 500MB (all heavy processing delegated to Intello)
