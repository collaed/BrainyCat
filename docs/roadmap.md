# BrainyCat Roadmap v2 — Full Feature Parity + Innovation

## Completed ✅

- Phase 1: Bilingual reader, sync maps, MOBI metadata
- Phase 2: pgvector, embeddings, similar books
- Phase 3: WebSocket activity, AI companion, collaborative annotations
- Phase 4: 53 tests, scanner/ISBN regex fixes

## Phase 5: MCP Server (Priority: HIGH)

Expose BrainyCat as an MCP (Model Context Protocol) server so AI clients
(Gemini, Claude, ChatGPT) can directly manage the library.

**Tools to expose:**
- `search_books(query)` — search library
- `get_book(id)` — full book details
- `enrich_book(id)` — trigger enrichment
- `similar_books(id)` — find similar
- `recommend(category)` — get recommendations
- `search_content(book_id, query)` — semantic search in book
- `recap(book_id)` — AI recap up to current position
- `ask(book_id, question)` — Q&A about book
- `classify(book_id)` — LLM genre classification
- `list_authors()` — browse authors
- `merge_authors(keep_id, merge_id)` — fix duplicates
- `create_series(name, book_ids)` — organize series
- `send_to_kindle(book_id)` — deliver to device
- `convert_tts(book_id)` — generate audiobook
- `library_stats()` — overview statistics
- `efficiency_dashboard()` — algorithm metrics

## Phase 6: Format Support (Priority: HIGH)

### 6.1 KFX Input/Output
- Amazon's current Kindle format (most requested Calibre plugin: 155K downloads)
- KFX is essentially a container of Ion binary data
- Input: parse KFX to extract text + metadata
- Output: not feasible without Amazon's toolchain — focus on input only
- Alternative: use Kindle Previewer CLI if available

### 6.2 AZW3/MOBI Enhanced Support
- AZW3 = KF8 (MOBI with HTML5) — parse EXTH + KF8 records
- MOBI metadata extraction already works (Phase 1)
- Add: cover extraction from MOBI/AZW3 thumbnail records
- Add: reading position from Kindle sidecar files (.sdr)

### 6.3 DeACSM (Adobe DRM → EPUB/PDF)
- Convert .acsm files to DRM-free EPUB/PDF
- Requires: Adobe Digital Editions account credentials
- Use: libgourou (open-source ACSM handler)
- Legal note: for personal backup of purchased books only

### 6.4 EPUB Merge/Split
- Merge: combine multiple EPUBs into one (anthology, collected works)
- Split: break EPUB at chapter boundaries
- Both via ebooklib manipulation (no external tools)

## Phase 7: Metadata & Quality (Priority: HIGH)

### 7.1 Goodreads Full Integration
- Import: shelves, ratings, reviews, reading dates from CSV
- Sync: match library books to Goodreads editions
- Metadata: scrape ratings, reviews, series info
- Social: import friends' recommendations

### 7.2 Count Pages/Words
- EPUB: count words per chapter, total word count
- PDF: count pages (already have via PyMuPDF)
- Store in books table: word_count, page_count, estimated_reading_time
- Display in book detail and list view

### 7.3 EPUB Quality Check (EpubCheck)
- Validate EPUB structure (OPF, NCX, content files)
- Check: broken internal links, missing images, invalid CSS
- Check: encoding issues, ID uniqueness, namespace correctness
- Report: per-book quality score with specific issues
- Auto-fix: common issues (missing NCX, broken links)

### 7.4 Amazon Multiple Countries
- Search Amazon .com, .co.uk, .de, .fr, .es, .it, .co.jp
- Use Google as proxy per country domain
- Merge results: pick best cover, most complete metadata
- Respect rate limits per domain

### 7.5 EPUB Linter
- CSS validation (unused rules, invalid properties)
- Image optimization (oversized images in EPUBs)
- Font embedding check
- Accessibility check (alt text, reading order)

## Phase 8: Device Integration (Priority: MEDIUM)

### 8.1 Kobo Support
- Detect Kobo device via USB/MTP
- Read: KoboReader.sqlite for reading progress, bookmarks, annotations
- Write: send books in KEPUB format
- Sync: import highlights and reading position

### 8.2 Kindle Device Import
- Read: Kindle sidecar files (.sdr) for annotations, bookmarks, clippings
- Parse: My Clippings.txt for highlights
- Import: reading position from Kindle
- Match: clippings to library books by title/author

### 8.3 Annotation Import from Devices
- Kindle: My Clippings.txt parser
- Kobo: KoboReader.sqlite annotations table
- Apple Books: parse annotation plist files
- Store: in annotations table with device source tag

## Phase 9: Cover & Display (Priority: MEDIUM)

### 9.1 Cover Generation Customization
- Settings page for cover preferences:
  - Fiction stripe: vertical (default), width, position
  - Non-fiction stripe: horizontal (default), height, position
  - Color overrides per genre
  - Font selection (serif/sans-serif/custom)
  - Background color/gradient
  - Show/hide: author, genre label, BrainyCat watermark
- Preview before applying
- Batch regenerate with new settings

### 9.2 Kindle Hi-Res Covers
- Download highest resolution covers from Amazon
- Use Google Images as fallback
- Store multiple resolutions (thumbnail, medium, full)

## Phase 10: AI & Intelligence (Priority: MEDIUM)

### 10.1 WordDumb (Kindle Word Wise + X-Ray)
- Word Wise: annotate difficult words with simple definitions
- X-Ray: extract characters, locations, terms → build reference card
- Generate: Kindle-compatible Word Wise and X-Ray files
- Use: LLM for definitions, NER for entity extraction

### 10.2 FanFicFare Integration
- Download fanfiction from: AO3, FFN, Wattpad, Royal Road
- Convert to EPUB with proper metadata
- Track: series, chapters, update notifications

### 10.3 Bulk Operations
- Bulk edit: select multiple books → change author/tags/series
- Bulk convert: select → convert all to PDF/EPUB
- Bulk enrich: select → trigger enrichment for all
- Bulk tag: select → apply/remove tags
- Bulk delete: already implemented ✅

## Phase 11: Infrastructure (Priority: LOW)

### 11.1 OPDS v2
- Pagination (page/offset)
- Faceted navigation (by author, tag, series, format)
- Search with OpenSearch descriptor
- Proper acquisition links per format
- Thumbnail links
- Compatible with: Moon+ Reader, KOReader, Librera, Calibre

### 11.2 Plugin System
- Python plugin interface: `class BrainyCatPlugin`
- Hooks: on_upload, on_enrich, on_convert, on_search
- Plugin directory with auto-discovery
- Settings per plugin
- Community plugin repository (future)

### 11.3 Custom Columns
- User-defined metadata fields (text, number, date, boolean, rating)
- Stored in JSONB extra_metadata
- Searchable and sortable
- Displayed in list view

## Priority Matrix

| Phase | Impact | Effort | Priority |
|-------|--------|--------|----------|
| 5. MCP Server | 🔥 High (AI integration) | Medium (2-3h) | **P0** |
| 6. Format Support | 🔥 High (user need #1) | High (days) | **P1** |
| 7. Metadata & Quality | 🔥 High (library quality) | Medium (hours) | **P1** |
| 8. Device Integration | Medium (niche) | High (days) | **P2** |
| 9. Cover Customization | Medium (UX) | Low (hours) | **P2** |
| 10. AI & Intelligence | Medium (innovation) | Medium (hours) | **P2** |
| 11. Infrastructure | Low (foundation) | Medium (hours) | **P3** |
