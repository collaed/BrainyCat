# BrainyCat — Roadmap v4

Last updated: 2026-04-23

## Completed ✅

### Core (Phases 1-4)
- Library CRUD, search, upload, collections, 5 UI skins
- EPUB reader (themes, night mode, dictionary, speed tracking, auto-scroll)
- PDF reader (pdf.js, progress tracking, lazy page rendering)
- MOBI/AZW3 reading (auto-converts to EPUB on first open)
- Audio player (chapters, speed, smart sleep mode, bookmark, download)
- 10 format conversions via ebook-convert
- OPDS 1.2 with pagination
- 53→210 tests (unit + integration + Playwright E2E)

### Intelligence
- 10 enrichment sources in parallel (Google Books, OL, OL Enhanced, LoC, Amazon 6-country, Gutendex, VIAF, ISNI, Inventaire, BookBrainz)
- Calibre-style merge + cover chain (Apple Books, Bookcover API) + dummy validation
- ISBN extraction: 9 languages, checksum validation, 40+ formats
- ISBN barcode scanning (pyzbar EAN-13 from scanned PDF back covers)
- Multi-ISBN storage (print, ebook, PDF, audiobook ISBNs with type detection)
- Edition detection (multilingual: English/French/German/Spanish)
- Full-text metadata extraction
- Content fingerprinting: Winnowing + MinHash + binary compare
- TF-IDF embeddings: 11-language stopwords, pgvector similarity
- Book Genome taste engine: 7 categories + NLP themes
- Readability: Flesch-Kincaid + Gunning Fog
- Calibre-aligned quality score (10-field weighted scoring, 100 max)
- Language extraction (EPUB OPF metadata + ISBN region inference)
- Missing data filter (ISBN, description, cover, tags, quality)
- Library health report: 10 checks
- Soundex author matching
- Adaptive chapter splitting (silence detection)
- Edition diffing (paragraph-level)

### AI (via Intello)
- AI companion, contextual footnotes, getAbstract summaries
- Word Wise + X-Ray, LLM genre classification
- Orpheus TTS, Whisper STT, OCR

### Catalog & Discovery
- 8 sources (120K+ free books), unified parallel search
- Gutenberg↔LibriVox cross-linking, local cache (175ms)
- Language preferences, "you already own this" detection
- OPDS import from external servers

### Social
- Federated reading profiles, book clubs, lending, streaks
- Annotation export to Markdown/Obsidian

### Integration
- MCP server: 28 tools
- ABS mobile app compatibility (full playback flow)
- Calibre sync plugin (two-way enrichment bridge)
- API key auth (Bearer through Caddy)

## Next: Ingest Pipeline (Priority: HIGH)

### P1: EPUB3 Canonical Storage
- All uploads converted to EPUB3 as internal canonical format
- Original file preserved alongside canonical copy
- Pipeline: upload → detect format → convert to EPUB3 → store both
- On-demand conversion for delivery (MOBI/KEPUB/PDF)
- **Why**: EPUB3 is the most open, richest, best-supported format

### P2: Auto-Clean on Ingest
- Strip publisher cruft (ads, DRM artifacts, tracking pixels)
- Fix encoding issues (Latin-1 → UTF-8)
- Validate EPUB structure (our epub_check)
- Normalize CSS (remove vendor prefixes, fix broken styles)
- Optimize images (resize oversized, compress)
- Generate missing TOC/NCX

### P3: Auto-Enrich Pipeline
- On upload: ISBN scan → parallel enrichment (10 sources) → merge
- Auto-apply: description, cover, genres, series, rating
- Quality score computed automatically
- Embedding generated for similarity search
- **No user action needed** — book arrives enriched

### P4: Calibre Auto-Push
- Enriched metadata pushed to Calibre via sync plugin
- Cleaned EPUB3 replaces original in Calibre library
- Covers, ISBNs, descriptions, genres all synced
- Pipeline: BrainyCat enriches → plugin pulls → Calibre updated

## Next: Calibre Deep Integration (Priority: HIGH)

### C1: Live Metadata.db Reader (Phase A)
- Point BrainyCat at Calibre's metadata.db (read-only)
- Query catalog data directly, no import/copy
- Intelligence data in PostgreSQL, keyed by Calibre book ID
- **Effort**: 2-3 days

### C2: Shadow Metadata Overlay (Phase B)
- BrainyCat enrichments stored as overlay
- Display: merge Calibre data + BrainyCat enrichments
- Pending changes queue with diff view
- **Effort**: 1-2 days

### C3: Content Server Proxy (Phase D)
- BrainyCat in front of calibre-server
- Passes catalog/download through unchanged
- Adds: taste recommendations, sleep detection, fingerprint warnings
- **Effort**: 3-5 days

### C4: Plugin Distribution
- Submit brainycat-sync.zip to Calibre plugin repo
- Documentation, screenshots, setup guide
- **Effort**: 1 day

## Next: Reader & Player (Priority: MEDIUM)

### R1: Comic Reader (CBZ/CBR)
- Page-turn interface for comic archives
- Would attract Kavita/Komga users

### R2: Annotation UI in Reader
- Highlight text → save annotation
- View others' shared annotations inline
- Currently annotations are API-only

### R3: Bookmarks UI
- Visual bookmark list in reader sidebar
- Jump to bookmarked positions

## Next: Intelligence Improvements (Priority: MEDIUM)

### I1: Real Sentence-Transformers
- Via Intello or local model (all-MiniLM-L6-v2, 80MB)
- "A story about loss" would match "A tale of grief"
- TF-IDF is good for same-topic, not semantic similarity

### I2: Series Completion via Open Library
- "You have books 1, 2, 4 of Expanse. Book 3 is Abaddon's Gate."
- Check availability: Gutenberg, LibriVox, OL lending, Standard Ebooks

### I3: Book DNA Card
- Shareable image: genres, hours read, streaks, favorite author
- Like Spotify Wrapped for books

### I4: Want-to-Read Sync
- Import from Open Library reading log
- Cross-reference: "You wanted 47 books — you own 12"

## Next: Library & Delivery (Priority: MEDIUM)

### L1: Bulk Operations UI
- Multi-select books for batch tagging, enrichment, deletion, conversion

### L2: Virtual Libraries (Saved Filter Presets)
- Save and recall filter combinations as named virtual libraries

### L3: Hierarchical Tag Browser
- Tree-structured tag navigation with parent/child relationships

### L4: Kindle Email Configuration
- In-app setup for Kindle email delivery addresses

### L5: OTA Delivery to E-Readers (OPDS Push)
- Push books directly to e-readers via OPDS

### L6: Audiobook Chapter Retagging + Format Optimization
- Re-tag chapter metadata and optimize audio format for playback

### L7: News Recipes (RSS→EPUB Scheduled)
- Scheduled conversion of RSS feeds into EPUB periodicals

## Next: Ecosystem (Priority: LOW)

### E1: Kavita/Komga OPDS Testing
- Verify our OPDS import works with their feeds
- Document setup for each server

### E2: KOReader/Moon+ Reader Testing
- Verify OPDS catalog works with popular reading apps
- Document connection setup

### E3: FanFicFare Integration
- Download from AO3, FFN, Wattpad, Royal Road
- Convert to EPUB3, auto-enrich

## Next: ebook-convert-rs Integration (Priority: MEDIUM)

### Status: 3,553 lines of Rust, actively developed

A Rust-based ebook converter that could reduce/eliminate the Calibre dependency.
Currently handles EPUB, MOBI, PDF, DOCX, HTML, TXT, SVG.

### Integration Plan

**Phase 1: Supplement (now)**
- Compile ebook-convert-rs as a single binary
- Add to Docker image alongside Calibre's ebook-convert
- Use for: EPUB→MOBI (Kindle delivery), DOCX→EPUB (upload), HTML→EPUB (feeds)
- Keep Calibre for: PDF→EPUB, Huffman MOBI, KF8/AZW3, obscure formats
- Fallback chain: ebook-convert-rs → Calibre ebook-convert → WeasyPrint

**Phase 2: Primary (when Huffman + KF8 are implemented)**
- ebook-convert-rs becomes the default converter
- Calibre becomes optional (for edge cases)
- Docker image shrinks by ~300MB

**Phase 3: Standalone (when font embedding + PDF metrics are done)**
- Full Calibre independence for conversion
- Calibre only needed for its plugin ecosystem and metadata sources

### What Works vs What's Missing

| Feature | ebook-convert-rs | Calibre | Gap |
|---|---|---|---|
| EPUB↔MOBI | ✅ PalmDOC + images | ✅ + Huffman + KF8 | 20% of MOBI files |
| EPUB↔PDF | ⚠️ No font embedding | ✅ Full | Font support |
| EPUB↔DOCX | ✅ WordprocessingML | ✅ Full | Edge cases |
| Performance | 🔥 10-50x faster | Baseline | Rust wins |
| Binary size | ~5MB | ~300MB | 60x smaller |
| DRM detection | ✅ Clear error | ✅ + plugin removal | Same |

## Architecture: Ingest Pipeline

```
Upload (any format)
    │
    ▼
Format Detection
    │
    ├─ EPUB? ──► Validate + Clean
    ├─ PDF? ───► Store as-is + extract text
    └─ Other? ─► ebook-convert → EPUB3
                    │
                    ▼
              Canonical EPUB3
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
ISBN Scan     Cover Chain     Enrichment (10 sources)
    │               │               │
    └───────────────┼───────────────┘
                    ▼
              Merge + Quality Score
                    │
                    ▼
              Writeback into EPUB3
                    │
                    ▼
              Store in PostgreSQL
                    │
                    ▼
              Push to Calibre (via plugin)
```

## Architecture: Calibre Companion

```
┌─────────────────────┐     ┌──────────────────────────┐
│     Calibre          │     │      BrainyCat            │
│                      │     │                          │
│  metadata.db ◄──READ──────── catalog queries          │
│  book files  ◄──READ──────── file serving             │
│                      │     │                          │
│  db.new_api ◄──PLUGIN──────── enriched metadata       │
│  (safe writes)       │     │  cleaned EPUB3           │
│                      │     │  covers, ISBNs, genres   │
│                      │     │                          │
│                      │     │  PostgreSQL:             │
│                      │     │  - fingerprints          │
│                      │     │  - embeddings            │
│                      │     │  - taste profiles        │
│                      │     │  - sleep events          │
│                      │     │  - reading progress      │
│                      │     │  - social/clubs          │
│                      │     │  - MCP tools             │
└─────────────────────┘     └──────────────────────────┘
```
