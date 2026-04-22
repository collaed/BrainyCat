# BrainyCat Roadmap v3

## Completed ✅

| Phase | Features | Status |
|-------|----------|--------|
| 1 | Project scaffolding, 33-table schema, Docker, Caddy | ✅ |
| 2 | Auth (X-Auth-User + cookie + Bearer + OAuth stubs) | ✅ |
| 3 | Book upload, EPUB/PDF/audio extraction, CRUD, search | ✅ |
| 4 | Collections, book linking, shelves | ✅ |
| 5 | Library UI (grid/list, search, upload, drag-drop) | ✅ |
| 6 | Metadata enrichment (5 sources), Calibre-style merge | ✅ |
| 7 | Incoming folder scanner | ✅ |
| 8 | Library intelligence (authors, series, quality, dupes) | ✅ |
| 9 | EPUB reader (epub.js, progress, themes, genre margins) | ✅ |
| 10 | Audio player (chapters, speed, sleep timer, Media Session) | ✅ |
| 11 | Audio restoration (7 ffmpeg profiles) | ✅ |
| 12 | TTS ebook→audiobook (Piper, per-chapter MP3s) | ✅ |
| 13 | STT audiobook→ebook (via Intello Whisper) | ✅ |
| 14 | Format conversion (EPUB→PDF via WeasyPrint) | ✅ |
| 15 | Gutenberg + LibriVox catalog with import | ✅ |
| 16 | Translation (5 backends: Argos, DeepL, Google, LLM, Ollama) | ✅ |
| 17 | Bilingual reader (aligned paragraphs, synced scroll) | ✅ |
| 18 | Text↔audio sync maps (generated during TTS/STT) | ✅ |
| 19 | Recommendations (pgvector cosine similarity) | ✅ |
| 20 | AI companion (semantic search, recap, Q&A, auto-tag) | ✅ |
| 21 | Reviews aggregation (Google Books, Open Library) | ✅ |
| 22 | Stats (genres, authors, personality, language) | ✅ |
| 23 | Import (Calibre, Goodreads CSV, audiobookshelf) | ✅ |
| 24 | OPDS v2 (pagination, OpenSearch, per-format links) | ✅ |
| 25 | CLI tool | ✅ |
| P1 | Bilingual reader content loading | ✅ |
| P2 | pgvector, embeddings, similar books | ✅ |
| P3 | WebSocket activity, collab annotations | ✅ |
| P4 | 53 tests, scanner/ISBN regex fixes | ✅ |
| P5 | MCP server (16 tools), API key auth | ✅ |
| — | ISBN extraction (9 languages, EU legal) | ✅ |
| — | Content fingerprinting (winnowing + MinHash) | ✅ |
| — | Cover generation + optimization | ✅ |
| — | Metadata writeback into EPUB OPF | ✅ |
| — | Efficiency dashboard | ✅ |
| — | MOBI metadata extraction (EXTH records) | ✅ |
| — | Page/word count | ✅ |
| — | Bulk tag, bulk enrich | ✅ |
| — | OCR via Intello (job-based, searchable PDF) | ✅ |
| — | LLM genre classification (Thema codes) | ✅ |
| — | Amazon metadata (Google proxy, IPv6) | ✅ |
| — | Series detection from Google Books/Amazon | ✅ |
| — | Kindle delivery (EPUB or PDF for workbooks) | ✅ |
| — | Podcast RSS feeds | ✅ |
| — | Signal notifications | ✅ |
| — | Background scheduler (6 processes) | ✅ |

## Next: Immediate (This Week)

### N1: EPUB Quality Check
- Validate OPF structure, NCX, content references
- Check: broken links, missing images, encoding issues
- Auto-fix common problems (missing NCX, broken hrefs)
- Quality score integration (affects book quality_score)
- **Effort**: 3h

### N2: EPUB Linter + Cleanup
- CSS: find unused rules, invalid properties
- Images: detect oversized images, offer optimization
- Fonts: check embedding, suggest subsetting
- Accessibility: alt text, reading order
- **Effort**: 3h

### N3: Count Pages Batch + Display
- Run page/word count on all books (background)
- Show in list view and book detail
- Estimated reading time in hours/minutes
- **Effort**: 1h (mostly wiring — counting works)

### N4: Goodreads Full Integration
- Import shelves, ratings, reading dates from CSV (already partial)
- Scrape series info from Goodreads pages
- Match library books to Goodreads editions by ISBN
- **Effort**: 3h

### N5: Amazon Multi-Country
- Search .com, .co.uk, .de, .fr, .es, .it
- Google proxy per country domain
- Merge: best cover, most complete metadata
- **Effort**: 2h

### N6: Bulk Edit UI
- Select multiple books in list view → "Edit Selected"
- Change: author, tags, series for all selected
- Bulk convert to PDF
- Bulk send to Kindle
- **Effort**: 3h

## Next: Short-Term (This Month)

### S1: KFX Input
- Parse Amazon KFX (Ion binary format)
- Extract: text, metadata, cover
- Use: Amazon's Kindle Previewer if available, else parse Ion directly
- **Effort**: 1-2 days (complex binary format)

### S2: AZW3 Enhanced
- Parse KF8 records (HTML5 in MOBI container)
- Extract cover from thumbnail record
- Reading position from .sdr sidecar files
- **Effort**: 1 day

### S3: DeACSM (Adobe DRM → EPUB)
- Integrate libgourou for ACSM file handling
- Requires: Adobe account credentials (one-time setup)
- Legal: personal backup only
- **Effort**: 1 day

### S4: EPUB Merge/Split
- Merge: combine EPUBs (anthology builder)
- Split: break at chapter boundaries
- Via ebooklib manipulation
- **Effort**: 3h

### S5: WordDumb (Word Wise + X-Ray)
- Word Wise: annotate difficult words with definitions (LLM)
- X-Ray: extract characters, locations, terms → reference card
- Generate Kindle-compatible files
- **Effort**: 1 day

### S6: Kobo Support
- Detect Kobo via USB/MTP (if server has USB access)
- Read KoboReader.sqlite for progress, annotations
- KEPUB output format
- **Effort**: 1-2 days

### S7: Kindle Annotation Import
- Parse My Clippings.txt
- Parse .sdr sidecar files
- Match to library books
- Import as annotations
- **Effort**: 3h

### S8: Cover Customization Settings
- Settings page: colors per genre, stripe width/position
- Font selection, background options
- Show/hide elements (author, genre label, watermark)
- Preview before batch regenerate
- **Effort**: 3h

### S9: FanFicFare
- Download from AO3, FFN, Wattpad, Royal Road
- Convert to EPUB with metadata
- Track series/chapters, update notifications
- **Effort**: 1 day

## Next: Medium-Term (Next Month)

### M1: Plugin System
- Python plugin interface with hooks
- Auto-discovery from plugins/ directory
- Per-plugin settings
- **Effort**: 2 days

### M2: Custom Columns
- User-defined fields (text, number, date, boolean, rating)
- Stored in JSONB extra_metadata
- Searchable, sortable, displayed in list view
- **Effort**: 1 day

### M3: Virtual Libraries
- Saved search queries as "virtual libraries"
- Quick switch between views
- Per-user virtual libraries
- **Effort**: 3h

### M4: Real-Time Collaboration v2
- Live cursors in reader (see where others are reading)
- Book club mode: shared reading sessions
- Discussion threads per book/chapter
- **Effort**: 2 days

### M5: Mobile App (PWA)
- Progressive Web App manifest
- Offline reading (service worker + cached EPUBs)
- Push notifications for new books
- **Effort**: 1 day

## Architecture Notes

### Current Stack
- **Backend**: Python 3.12, FastAPI, asyncpg, PostgreSQL 16 + pgvector
- **Frontend**: Vanilla HTML/JS/CSS, EPUB.js, Chart.js
- **AI**: Intello (TTS, STT, OCR, LLM × 13 providers)
- **MCP**: 16 tools, Bearer auth, stdio transport
- **Background**: 6 concurrent processes (enrichment, ISBN, fingerprints, embeddings, writeback, dupes)
- **Image**: 1.7GB Docker (ffmpeg, sox, espeak-ng, Piper TTS, WeasyPrint, PyMuPDF)

### Metrics (as of 2026-04-22)
- 1,617 books, 1,052 authors, 5 series
- 1,310 ISBNs (81%), 964 enriched (60%)
- 350 fingerprinted, 100 embedded
- 53 tests, 55 Python modules, ~10K lines
- 7 background processes, 7 metadata sources
- 16 MCP tools, 4-layer auth
