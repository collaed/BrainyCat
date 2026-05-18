# BrainyCat Roadmap

## Current State (v1.0 — April 2026)

**58+ features implemented.** Feature-complete for r/selfhosted launch.

- 1,718 books in production library
- 32 metadata sources, continuous enrichment
- Full web reader (EPUB/PDF/MOBI) with annotations
- Audio player with chapter merge + TTS
- 12 AI features (Ask Book, Recap, Mind Maps, Auto-tag, etc.)
- 9 sync protocols (OPDS, KOReader, Kobo, WebDAV, ABS, MCP, WebSocket, Podcast RSS, OPDS-PS)
- 10 experimental features with side-by-side evaluation framework

---

## v1.1 — Polish & Stability (May 2026)

Focus: Launch readiness, first-impression quality.

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | Mobile-responsive grid improvements | Low | TODO |
| 2 | Custom error pages (404, 500) | Low | TODO |
| 3 | Rate limiting on public endpoints | Low | TODO |
| 4 | Reading challenges criteria filtering | Low | Partial (table exists) |
| 5 | Duplicate page removal UI (keep/discard) | Low | Detection done |
| 6 | AI cover generation (placeholder for books without covers) | Medium | TODO |
| 7 | Onboarding tour (first-time user walkthrough) | Medium | TODO |
| 8 | **Full-text search indexing** (PostgreSQL tsvector + ts_rank) | Medium | TODO |
| 9 | **Consumption rules** (regex/pattern matching on filenames → auto-tag, set publisher) | Medium | TODO |
| 10 | **OIDC/OAuth authentication** (Google, GitHub, generic OIDC) | Medium | TODO |
| 11 | **Annotation sharing** between users on same server | Low | TODO |
| 12 | **Obsidian export** for annotations and highlights | Low | TODO |
| 13 | **Email consumption** (IMAP inbox → auto-import ebooks) | Medium | TODO |
| 14 | **i18n** — multi-language UI (FR, DE, ES at minimum) | Medium | TODO |
| 15 | **UI framework migration** — Svelte SPA with proper routing and state | High | TODO |
| 16 | **ML-based auto-tagging** (train classifier on user's validated tags) | High | TODO |
| 17 | **Comics/manga support** (ComicInfo.xml parsing, webtoon reader mode) | Medium | TODO |
| 18 | **Smart filters** bindable to homescreen (Kavita-style) | Low | TODO |
| 19 | **Reading lists** with sharing between users | Low | TODO |
| 20 | **Dedicated readers per format** (dual-page spread, webtoon mode) | Medium | TODO |

---

## v1.2 — Audio & Sync (June 2026)

Focus: Audio features, deeper device sync.

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | Chapter detection for monolithic audiobooks (ML silence detection) | Medium | TODO |
| 2 | Text↔Audio sync UI (Whispersync — Intello /api/v1/align) | High | Endpoint ready |
| 3 | Voice cloning for personalized TTS (XTTS via Intello) | High | Intello wishlist |
| 4 | Kobo deep sync (full API: shelves, bookmarks, annotations) | Medium | Basics done |
| 5 | ABS mobile app: offline download, chapter images | Medium | Compat shim done |

---

## v2.0 — Multi-User & Intelligence (July–September 2026)

Focus: Team/family use, knowledge management.

### Multi-User (R2.1)
| # | Feature | Effort |
|---|---|---|
| 1 | Per-user library isolation (visibility rules) | High |
| 2 | Shared vs private books | Medium |
| 3 | Family library with parental controls | Medium |
| 4 | User roles: admin, member, guest | Low |

### Reading Intelligence (R2.7)
| # | Feature | Effort |
|---|---|---|
| 1 | Intelligence pages with 3-tier memory (session/book/lifetime) | High |
| 2 | Cross-book knowledge graph (entities, themes, connections) | High |
| 3 | "This book references..." — automatic citation detection | Medium |
| 4 | Reading patterns analysis (time of day, genre cycles) | Medium |

### Infrastructure (R2.10)
| # | Feature | Effort |
|---|---|---|
| 1 | Alembic migrations (replace raw SQL) | Medium |
| 2 | mypy strict typing | Medium |
| 3 | Test suite (pytest, 80%+ coverage) | High |
| 4 | Scheduler separation (Celery or arq) | Medium |
| 5 | Redis caching for OCR intermediate results | Low |

---

## v2.1 — Federation & Community (October 2026)

Focus: Social reading, cross-instance sharing.

| # | Feature | Effort |
|---|---|---|
| 1 | Federated profiles (ActivityPub) | High |
| 2 | Book clubs with pace-locked chapters | Medium |
| 3 | OAI-PMH protocol (metadata harvesting for libraries) | Medium |
| 4 | Prowlarr integration (auto-download wanted books) | Medium |
| 5 | Reading challenges: community-wide, leaderboards | Medium |
| 6 | Contribute enriched metadata back to Open Library (live) | Low |

---

## v3.0 — Advanced AI (2027)

Focus: Deep AI integration, research tools.

| # | Feature | Effort |
|---|---|---|
| 1 | PDF reflow (deconstruct into reflowable text) | High |
| 2 | Suffix array dedup (substring-level duplicate detection) | Medium |
| 3 | Book DNA: Spotify Wrapped with AI-generated insights | Medium |
| 4 | Research mode: citation graph, bibliography extraction | High |
| 5 | MARC Z39.50 client (query real library catalogs) | Medium |
| 6 | Semantic search across full library text (pgvector embeddings) | High |
| 7 | Auto-generated study guides from textbooks | Medium |

---

## v2.2 — Writing & Creative Tools (November 2026)

Focus: Bridge reading and writing, story planning.

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | Story Graph templates (Save the Cat, Hero's Journey, 3-Act) | Low | TODO |
| 2 | Story Graph → outline export (Markdown, Scrivener) | Low | TODO |
| 3 | Character relationship graph (visual, from Book NLP) | Medium | NLP done, graph TODO |
| 4 | Writing prompts from reading (LLM generates prompts from highlights) | Low | TODO |
| 5 | Comparative literature analysis (theme overlap across books) | Medium | Similar passages done |
| 6 | Book-to-book influence mapping ("This book references...") | High | TODO |

---

## v3.0 — Advanced AI & Research (2027)

Focus: Deep AI integration, academic tools.

| # | Feature | Effort |
|---|---|---|
| 1 | PDF reflow (deconstruct into reflowable text) | High |
| 2 | Suffix array dedup (substring-level duplicate detection) | Medium |
| 3 | Semantic search across full library text (pgvector embeddings) | High |
| 4 | Auto-generated study guides from textbooks | Medium |
| 5 | Citation graph extraction (bibliography → linked books) | High |
| 6 | MARC Z39.50 client (query real library catalogs) | Medium |
| 7 | Book DNA: Spotify Wrapped with AI-generated narrative insights | Medium |
| 8 | Spaced repetition from highlights (Anki-style flashcards) | Medium |
| 9 | Reading comprehension quizzes (auto-generated from content) | Medium |

---

## Ideas Parking Lot

Not scheduled, evaluate when relevant:

### From community feedback (Kavita/Calibre-Web/Reddit/Lemmy issues)

- **OPDS-PS (Page Streaming)** — users want to read directly from OPDS without downloading (KOReader, Foliate)
- **Kindle-friendly browser UI** — simplified interface for Kindle's experimental browser (Calibre-Web #2723)
- **E-ink optimized mode** — high contrast, no animations, large touch targets
- **Readwise integration** — export highlights to Readwise → Obsidian (most requested sync)
- **WebDAV library access** — users want to mount library as WebDAV for any reader app
- **Bulk metadata editor** — select 20 books, change author/publisher/tags in one go
- **Cover aspect ratio normalization** — auto-crop/resize covers to consistent 2:3
- **Reading time estimates** — "3h 42min" based on word count and user's reading speed
- **"Continue reading" shelf** — prominent on homepage, shows last 5 in-progress books
- **Download all formats** — one-click ZIP of all formats for a book
- **Duplicate detection UI** — side-by-side comparison with merge button
- **Import from Goodreads/StoryGraph** — CSV import of reading history + ratings
- **Progress sync across devices** — the #1 most requested feature everywhere
- **Dark/light/sepia reader themes** — with per-book memory
- **Offline PWA** — service worker for reading without internet
- **Kobo sync** — full bidirectional (Calibre-Web's most complex feature)
- **PDF reflow** — convert scanned/fixed-layout PDF to reflowable EPUB
- **Audiobook chapter detection** — silence-based splitting for monolithic MP3s
- **Book lending between users** — with return dates and notifications
- **Reading challenges** — "50 books in 2026" with community leaderboards

### Features that can be off by default (toggle in settings)

- Full-text search indexing (`enable_fts`)
- Email consumption (`enable_email_import`)
- OCR pipeline (requires Intello)
- AI features (companion, explain, translate — requires Intello)
- Social features (federation, book clubs)
- MCP server
- Podcast RSS feeds
- TTS generation
- Content fingerprinting (CPU-intensive)
- Automatic format conversion on import

---

## Principles

1. **AI-first but graceful degradation** — everything works without Intello, AI features just disappear
2. **One entry, multiple formats** — EPUB + PDF + audiobook = one book
3. **Continuous enrichment** — never stop improving metadata quality
4. **Experimental framework** — evaluate new algorithms side-by-side before committing
5. **Protocol polyglot** — support every sync protocol readers use
6. **Self-hosted sovereignty** — no cloud dependencies, no telemetry, AGPL-3.0

---

## Testing Plan

Every module must have tests covering: happy path, edge cases, error handling, and integration.

### Unit Tests (pytest, per module)

| Module | Tests required |
|--------|---------------|
| `isbn.py` | Valid ISBN-10/13, unicode dashes, invalid checksums, extraction from filenames, barcode decode mock |
| `metadata.py` | Merge logic (shortest title, longest desc), relevance guard rejection, empty results |
| `watcher.py` | File import, duplicate skip, extension filtering, debounce, consumption rules application |
| `filename_history.py` | Alignment computation (identical=100%, completely different=0%), record/revert |
| `content_guard.py` | Language detection (FR/EN/DE samples), genre detection, insufficient text handling |
| `sentence_match.py` | Sentence extraction, unusual sentence picking, Google API mock (1 result, many results, 0 results) |
| `format_stack.py` | Same ISBN detection, title similarity threshold, fingerprint verification mock |
| `series_detect.py` | All regex patterns (Book 1, Tome 3, #2, Vol. 4), gap detection, missing search |
| `consumption_rules.py` | Regex matching, all action types (tag, publisher, language, genre, skip), priority ordering |
| `organize.py` | Path sanitization, genre/author/title tree, collision handling |
| `search_index.py` | Indexing, search ranking, snippet generation, empty results |
| `calibre_library_import.py` | OPF parsing, title matching, cover copy, author linking |
| `comicinfo.py` | Full ComicInfo.xml parsing, missing fields, manga flag |
| `email_consume.py` | IMAP mock, attachment extraction, allowed extensions, filename decoding |
| `auth.py` | Session cookie, API key, header auth, expired session, bcrypt verify |
| `books.py` | Upload, list with filters, search, delete, cover serving |
| `metadata_audit.py` | Record change, validate (delete), flag (create bug), get_pending |

### Integration Tests

| Scenario | What it tests |
|----------|---------------|
| Full import pipeline | Drop file in incoming → watcher picks up → extract metadata → consumption rules → content guard → DB record |
| Enrichment cycle | Book with ISBN → query sources → merge → writeback → quality score update |
| Format stacking | Import same book as EPUB + PDF → fingerprint → auto-merge → single record with 2 formats |
| OCR submission | PDF without text → submit to Intello → poll → receive result → update book |
| Series detection | Import "Harry Potter 1" + "Harry Potter 3" → detect series → show gap at #2 |
| Sentence fallback | Book with no ISBN, garbled title → sentence match → identify → update metadata |

### E2E Tests

| Flow | Steps |
|------|-------|
| New user setup | Visit / → setup wizard → create admin → redirect to library |
| Upload and read | Login → upload EPUB → appears in grid → click → read in reader → progress saved |
| Bulk enrichment | Select 5 books → click Enrich → jobs run → quality scores update → covers appear |
| Metadata review | Enrichment changes title → appears in Ops page → admin validates → history cleared |
| Flag and revert | Enrichment makes bad change → admin flags → bug created → admin reverts via filename history |

### Running Tests

```bash
make test          # Unit tests (fast, no network)
make test-int      # Integration tests (needs PostgreSQL)
make test-e2e      # E2E tests (needs running instance)
make test-all      # Everything
```
