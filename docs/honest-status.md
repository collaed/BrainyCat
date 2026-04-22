# BrainyCat — Honest Status

## What's real and working (verified on live deployment)

- **Library**: 1603 books, CRUD, search (ILIKE + tsvector + pg_trgm), upload, collections
- **Reader**: EPUB.js with progress tracking, themes, genre margins, TOC
- **Audio player**: Chapter nav, speed, sleep timer, smart sleep mode, volume, bookmark
- **Format conversion**: 9 paths via Calibre's ebook-convert (EPUB↔MOBI/AZW3/PDF/TXT/DOCX)
- **Metadata enrichment**: 5 sources (Google Books 22%, Open Library 4%, Gutendex, LoC, Amazon)
- **ISBN extraction**: 9 languages, 83% coverage
- **Content fingerprinting**: Winnowing + MinHash, 350 books fingerprinted
- **TF-IDF embeddings**: Real (not semantic — "loss" won't match "grief", but same-topic books cluster)
- **Similar books**: pgvector cosine similarity (Sleeping Beauty → all 4 Beauty series books)
- **MCP server**: 28 tools, Bearer auth, tested with curl
- **OPDS**: Pagination, OpenSearch, per-format acquisition links
- **Taste engine**: 7 categories, CineCross-derived, NLP theme extraction
- **Calibre import**: Schema v1-v26+ compatible, tested with synthetic DBs
- **ABS compat**: Mobile app can connect, browse 1603 books, start playback sessions
- **Tests**: 199 (144 unit + 22 integration + 33 Playwright E2E), all against live deployment

## What's a skeleton / limited

- **Custom columns**: Type validation works, search works, but no tag browser or template language
- **Virtual libraries**: Saved queries, no UI yet
- **Plugin system**: Hook framework exists, no community plugins yet
- **Federated social**: Hash generation + public feed work, cross-instance following untested
- **Book clubs**: DB schema + API exists, no UI
- **Lending**: Request/approve flow exists, no cross-instance testing
- **Contextual footnotes**: Depends on Intello LLM being available

## What depends on external tools

- **Format conversion**: Requires Calibre's ebook-convert (included in Docker image)
- **KFX input**: Uses ebook-convert to convert KFX→EPUB, then extracts. No native Ion parser.
- **DeACSM**: Requires libgourou (NOT in Docker image — manual install needed)
- **TTS**: Requires Intello (Piper/Orpheus) or falls back to espeak-ng (low quality)
- **STT/OCR**: Requires Intello
- **AI features** (footnotes, Word Wise, X-Ray, classify): Require Intello LLM

## What we don't do that Calibre does

- Native format parsing for all 40+ formats (we use ebook-convert)
- Template language for custom columns
- Tag browser with hierarchical navigation
- Content server with user management UI
- Newspaper/recipe downloading
- Plugin marketplace (we have the framework, not the ecosystem)

## What we do that nobody else does

- Federated reading profiles (privacy-preserving social)
- Smart sleep mode (behavioral dead-man's-switch)
- Book Genome taste engine (7 categories)
- MCP server (28 tools for AI clients)
- ABS mobile app compatibility
- Content fingerprinting (winnowing + MinHash)
- Edition diffing (paragraph-level)
- Readability scoring (Flesch-Kincaid)
- Adaptive chapter splitting (silence detection)
- 5 switchable UI skins
