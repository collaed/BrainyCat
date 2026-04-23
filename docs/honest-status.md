# BrainyCat — Honest Status

Last updated: 2026-04-23

## What's Real and Working (verified on live deployment)

### Core Library
- 1,603 books, CRUD, search (ILIKE + tsvector + pg_trgm), upload, collections
- 10 format conversions via Calibre ebook-convert (EPUB↔MOBI/AZW3/PDF/TXT/DOCX)
- OPDS 1.2 with pagination, OpenSearch, per-format acquisition links
- 5 UI skins (Classic, Spreadsheet, Cockpit, Notebook, Canvas)

### Reading & Listening
- EPUB.js reader: progress tracking, themes (dark/light/sepia/night), genre margins, TOC
- Tap-to-define dictionary (dictionaryapi.dev), reading speed tracking, auto-scroll
- Night mode with blue light filter
- Audio player: chapters, speed, volume, bookmark, download
- Smart sleep mode: behavioral dead-man's-switch with adaptive chimes

### Intelligence (our unique value)
- 10 enrichment sources queried in parallel (Google Books, OL, OL Enhanced, LoC, Amazon, Gutendex, VIAF, ISNI, Inventaire, BookBrainz)
- Calibre-style merge: shortest title, longest description, averaged ratings
- Cover chain: enrichment → Apple Books → Bookcover API → OL → generate
- Dummy cover validation (MD5 check against known Google Books placeholders)
- ISBN extraction: 9 languages, checksum validation, 40+ formats via ebook-convert
- Content fingerprinting: Winnowing + MinHash + binary compare (file size pre-filter)
- TF-IDF embeddings: 11-language stopwords, pgvector cosine similarity
- Book Genome taste engine: 7 categories (DNA, Author, Community, Hidden Gems, Series, Anti + NLP themes)
- Readability scoring: Flesch-Kincaid + Gunning Fog + reading time estimates
- Library health report: 10 checks (covers, ISBNs, descriptions, authors, language, duplicates, series)
- Soundex matching for author dedup

### AI Features (require Intello)
- AI companion: semantic search, recap, Q&A
- Contextual footnotes: LLM-generated historical/cultural annotations
- getAbstract-style summaries: executive summary, key takeaways, actionable insights
- Word Wise + X-Ray: vocabulary definitions, character/location extraction
- LLM genre classification (Thema codes)
- Auto-tagging

### Catalog & Discovery
- 8 sources: Gutenberg (70K), LibriVox (20K), Standard Ebooks (800), Open Library, OAPEN (30K), OpenStax, Open Textbook Library (1.2K), GitHub
- Unified search: all sources in parallel, grouped by type (ebooks/audiobooks/textbooks/GitHub)
- Gutenberg↔LibriVox cross-linking (116 pre-computed pairs)
- Local catalog cache for instant search (175ms vs seconds)
- Language preferences filter catalog sync
- "You already own this" detection (ISBN + title + fuzzy matching)
- OPDS import from external servers (calibre-server, Kavita, Komga)

### Social & Collaboration
- Federated reading profiles: shareable hash, public feed, cross-instance following
- Book clubs: pace-locked chapters, spoiler-safe discussions
- Cross-library lending: request/approve flow, time-limited tokens
- Reading streaks & challenges (Duolingo-style)
- Annotation export to Markdown/Obsidian

### Integration
- MCP server: 28 tools for AI client management
- ABS mobile app compatibility: login, browse, playback sessions, progress sync
- Calibre sync plugin: two-way enrichment bridge via db.new_api
- API key auth (Bearer tokens through Caddy)
- Kindle delivery, podcast RSS, Signal notifications

### Testing
- 165 unit tests across 38 test files
- 22 integration tests hitting live endpoints
- 33 Playwright E2E tests (real browser, real server)
- All tests against live deployment — no mocks

## What's a Skeleton / Limited

- **Custom columns**: Type validation works, no tag browser or template language
- **Virtual libraries**: Saved queries, no UI
- **Plugin system**: Hook framework, no community plugins
- **Book clubs**: API exists, no UI
- **Lending**: Request/approve flow, no cross-instance testing
- **DeACSM**: Requires libgourou (not in Docker image)

## What Depends on External Tools

- **Format conversion**: Calibre ebook-convert (in Docker)
- **KFX input**: ebook-convert for KFX→EPUB conversion
- **TTS**: Intello (Orpheus/Piper) or espeak-ng fallback
- **STT/OCR**: Intello
- **AI features**: Intello LLM
- **Dictionary**: dictionaryapi.dev (free, no auth)

## What We Deliberately Don't Do

- Native format parsing for 40+ formats (use ebook-convert)
- EPUB editing (Calibre + Sigil's domain)
- Plugin marketplace (no community yet)
- Template language (read Calibre's custom columns instead)
- Device drivers (assume WiFi/web)
- 3D bookshelf view (skins handle UI variety)
