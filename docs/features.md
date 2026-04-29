# BrainyCat — Complete Feature Reference

## Overview

BrainyCat is a self-hosted AI reading companion for ebooks and audiobooks. It enriches your library from 32 metadata sources, provides a full web reader with annotations, and uses AI for intelligent features like Q&A, mind maps, and reading recaps.

**Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL 16 (pg_trgm, pgvector), vanilla HTML/JS, Docker

---

## 1. Library Management

### Upload & Ingest
- **22 formats supported:** EPUB, PDF, MOBI, AZW3, KFX, FB2, DOCX, ODT, TXT, RTF, HTML, MD, DJVU, CBZ, CBR + audio (MP3, M4B, FLAC, OGG)
- **Streaming upload:** 1MB chunks, never loads entire file into memory
- **Corruption check:** Rejects zero-filled files, broken PDFs, invalid EPUBs on upload
- **Pamphlet detection:** Flags PDFs <10 pages + <256KB as pamphlets
- **EPUB auto-fix on ingest:** Adds UTF-8 declaration, language tag, removes stray `<img>`, fixes NCX links
- **ZIP upload:** Upload a ZIP of multiple books, auto-extracted and imported individually
- **File watcher:** Polls `/data/incoming` every 10 seconds, auto-imports new files (Samba/NFS compatible)
- **Import from URL:** `POST /api/v1/import/url {url}` — server downloads and imports directly

### Organization
- **Quality score:** Calibre-aligned 10-field weighted scoring (0-100)
- **Book status:** Want to Read / Reading / Finished / Abandoned / Library Only — with timestamps
- **Series auto-detection:** 5 regex patterns scan titles for "Book 1", "Vol. 2", "#3", "Tome 4", "(Series #5)"
- **Collections:** User-created groups (POST /api/v1/collections) — "PhD Research", "Gift Ideas", "Book Club Q2"
- **Magic Shelves:** 12 dynamic views with live counts (Recently Added, Unread, High Quality, No ISBN, etc.)
- **Book lending tracker:** Record who borrowed your physical books, mark as returned

### Bulk Operations
- Multi-select for batch tagging, enrichment, deletion, conversion
- Smart merge: detect ISBN-based duplicates, consolidate files/annotations into one entry
- Merge candidates endpoint: `GET /api/v1/merge/candidates`

### Import Sources
- **Calibre library:** Reads `metadata.db` SQLite directly — imports title, authors, tags, description, ISBN
- **Goodreads/StoryGraph CSV:** Parses export file, maps shelves to reading status, matches existing books
- **Kindle Clippings:** Parses `My Clippings.txt`, extracts highlights/notes, auto-matches to library books
- **GitHub repos:** Authenticated recursive import of ebook files from repositories

---

## 2. Metadata Enrichment

### Sources (32 total)
- **Global:** Google Books (API key, 1000/day), Open Library (Works API + Ratings), Gutendex, Library of Congress, WorldCat, VIAF, ISNI
- **Regional:** BnF 🇫🇷, DNB 🇩🇪, BNE 🇪🇸, British Library 🇬🇧, Rakuten 🇯🇵, NDL 🇯🇵, Douban 🇨🇳
- **Social:** StoryGraph, Hardcover, Babelio, Skoob, ComicVine, MyAnimeList
- **Commercial:** Amazon (12 countries), Edelweiss, Thalia, BOL.com, Casa del Libro
- **Covers:** Google Images, Apple Books, Bookcover API
- **Unified:** Intello `/api/v1/lookup` queries Google Books + Open Library + OPDS in parallel

### How It Works
1. **Scheduler** runs continuously, picks 3 books at a time (least-tried-first, quality ASC)
2. **Row locking** with `FOR UPDATE SKIP LOCKED` prevents duplicate work
3. **Smart routing:** ISBN region detection routes French books to BnF first, German to DNB
4. **Title variants:** Strips publisher prefixes, dots→spaces, removes years, extracts from "Author - Title" patterns
5. **Deep enrichment:** LLM identifies correct title → APIs verify with cleaned query
6. **Auto-writeback:** After enrichment, metadata written back into EPUB file
7. **Contribution:** Checks Open Library, flags what we can push back (dry-run mode)

### ISBN Intelligence
- **6 extraction methods:** OPF metadata, full-text scan, barcode decode (pyzbar), filename, title, check-digit completion
- **Multi-ISBN storage:** print, ebook, PDF, audiobook ISBNs with type detection
- **Unicode dash handling:** `978‐1‐118‐99094‐0` (U+2010) → `9781118990940`
- **285 registration groups:** Official ISBN Range Message for region/language detection
- **BISAC/Thema codes:** Auto-mapped from tags, LLM verification for edge cases

---

## 3. Reading

### EPUB Reader
- **Engine:** epub.js with smooth scrolling, scrolled-doc mode
- **Themes:** Dark, Light, Sepia, Night
- **Fonts:** System, Serif, Sans, Monospace, OpenDyslexic
- **Bionic Reading:** Toggle that bolds first letter of each word (ADHD/dyslexia support)
- **In-book search:** 🔍 button searches all spine items client-side
- **Dictionary:** Tap a word for definition (language-aware, tries book language first)
- **Custom CSS injection:** User stylesheets for accessibility
- **Progress tracking:** Auto-saves position on every page turn

### PDF Reader
- **Engine:** pdf.js with lazy page rendering
- **Dark mode:** CSS filter (invert + hue-rotate) on canvas
- **OPDS-PS page streaming:** Individual pages served as PNG at requested width
- **PDF comparison view:** Side-by-side original vs OCR with keep/discard buttons
- **Page-level serving:** `GET /api/v1/opds-ps/{book_id}/page/{num}?width=1200`

### MOBI/AZW3
- Auto-converts to EPUB on first open (transparent to user)

### Annotations
- **Stylus support:** Pressure-sensitive pen/highlighter overlay, per-page, synced
- **Clippings:** Highlight text → save/explain (LLM)/translate, export to Markdown
- **PDF annotation embedding:** Writes highlights INTO the PDF file (permanent, survives download)
- **Annotated download:** `GET /api/v1/books/{id}/download-annotated` — serves PDF with embedded highlights
- **Global Notebook:** `GET /api/v1/notebook?q=search` — all annotations + clippings across all books, searchable

### Audio
- **Player:** Chapter navigation, speed control, sleep timer, Media Session API
- **Chapter merge:** Multiple MP3s → single M4B with chapter markers (AAC 64k mono)
- **TTS:** Piper (local) + Groq/Voxtral (via Intello) for ebook → audiobook conversion
- **STT:** Groq Whisper for audiobook → text transcription
- **Podcast feed:** `GET /api/v1/podcast/{book_id}/feed.xml` — subscribe in any podcast app

---

## 4. AI Features (via Intello)

### Ask This Book
- `POST /api/v1/books/{id}/ask {question}`
- Extracts first ~4000 words from PDF/EPUB
- Sends to LLM with grounding prompt ("answer based only on book content")
- Returns answer with context word count

### Book Recap ("Where was I?")
- `POST /api/v1/books/{id}/recap`
- Reads text up to user's current progress percentage
- LLM generates 3-5 paragraph summary of what happened so far
- Perfect for resuming abandoned books after weeks/months

### AI Mind Maps
- `POST /api/v1/experimental/mind-map/{book_id}`
- Generates structured JSON mind map (4-6 branches, 2-4 children each)
- Based on book description + title + author
- Returns: `{title, branches: [{label, children: [{label}]}]}`

### Shareable Note Cards
- `POST /api/v1/experimental/share-card {text, book_title, author, theme}`
- Returns SVG image with styled quote, book attribution, BrainyCat branding
- Dark/light themes, auto text wrapping

### LLM-Powered Features
- **Title cleanup:** LLM identifies correct title from dirty filenames
- **BISAC/Thema mapping:** LLM verifies genre classification for edge cases
- **Clipping explanation:** Highlight text → "Explain this" via LLM
- **Translation:** Highlight text → translate to any language
- **5-layer JSON parsing:** direct → fence strip → brace extract → sanitize → regex fallback

---

## 5. Discovery & Catalogs

### Free Sources (15)
Gutenberg, Standard Ebooks, LibriVox, Internet Archive, Feedbooks, OAPEN, arXiv, Semantic Scholar, CORE, Unpaywall, DOAB, Loyal Books, ManyBooks, GitHub, OpenStax

### OPDS Subscriptions
- 8 pre-configured catalogs (75,000+ free books)
- Add custom OPDS feeds
- One-click import from any catalog

### Recommendations
- `GET /api/v1/recommendations/similar/{book_id}` — shared tag similarity
- `GET /api/v1/recommendations/for-you` — personalized based on reading history (weighted by tag frequency, excludes already-read)

### Web Search
- Via Intello SearXNG integration
- Search results importable directly to library

---

## 6. Sync & Compatibility

### KOReader Sync (kosync protocol)
- `POST /api/v1/kosync/users/create` — register
- `GET /api/v1/kosync/users/auth` — authenticate (x-auth-user + x-auth-key headers)
- `PUT /api/v1/kosync/syncs/progress` — update reading position
- `GET /api/v1/kosync/syncs/progress/{document}` — get position
- `PUT /api/v1/kosync/syncs/bookmarks` — sync highlights/notes (JSONB storage)
- `GET /api/v1/kosync/syncs/bookmarks/{document}` — retrieve annotations

### Kobo Sync
- `GET /api/v1/kobo/v1/initialization` — capabilities
- `GET /api/v1/kobo/v1/library/sync` — book list (EPUB/KEPUB)
- `PUT /api/v1/kobo/v1/library/{id}/state` — progress update
- Auth via Bearer token (user's api_key)

### OPDS Feed
- Compatible with Moon+ Reader, KOReader, Calibre
- Full catalog with search, pagination, covers

### OPDS-PS (Page Streaming)
- `GET /api/v1/opds-ps/{book_id}/manifest` — page count + URL template
- `GET /api/v1/opds-ps/{book_id}/page/{num}?width=1200` — single page as PNG
- Compatible with streaming readers (KOReader, Panels)

### Audiobookshelf Compatibility
- ABS mobile app shim: login, browse, play, sync

### Kindle Delivery
- Auto-send to Kindle after enrichment (configurable)
- `POST /api/v1/send-to-kindle/{book_id}`

### MCP Server (28 tools)
- search_books, get_book, edit_book, delete_book, similar_books
- enrich_book, batch_enrich, classify_book, search_content
- recap, ask_book, library_stats, efficiency, book_sources
- send_to_kindle, convert_tts, convert_format, merge_authors
- create_series, taste_recommendations, epub_check, epub_lint, count_pages

---

## 7. Reading Analytics

### Reading Streaks
- `GET /api/v1/reading/streak` — current streak, longest streak, total days read
- Calculated from reading_progress update timestamps

### Reading Goals
- `PUT /api/v1/reading/goal {year, target, type: 'books'|'minutes'}`
- `GET /api/v1/reading/goal` — progress with percentage

### Reading Stats
- `GET /api/v1/reading/stats` — week/month/total sessions and minutes

### Reading Time Estimator
- `GET /api/v1/books/{id}/reading-time`
- Calculates based on user's actual pace (minutes per page from reading_log)
- Accounts for current progress percentage
- Returns: pages_remaining, hours_remaining, pace_min_per_page

### Reading Speed Test
- `POST /api/v1/reading/speed-test {words, seconds}` — calibrate WPM
- `GET /api/v1/reading/speed` — get calibrated speed
- Stored in user preferences, used by time estimator

### Reading Heatmap
- `GET /api/v1/experimental/heatmap?days=365`
- Daily reading sessions + books touched (GitHub-style contribution graph)

### Book DNA / Wrapped
- `GET /api/v1/wrapped/{year}` — Spotify Wrapped-style yearly summary
- Books finished, total hours, top author, languages read

### Activity Feed
- `GET /api/v1/activity?limit=50`
- Timeline of enrichments, imports, and reading progress events

---

## 8. Authentication & Users

### Local Auth
- Username/password with bcrypt hashing
- Session cookies (httponly, 30-day expiry)
- First-run setup wizard

### OAuth/OIDC
- `GET /api/v1/auth/oauth/google` — Google login
- `GET /api/v1/auth/oauth/oidc` — Generic OIDC (Keycloak, Authentik, etc.)
- Auto-creates user on first OAuth login (email-based matching)
- Config: `BRAINYCAT_GOOGLE_CLIENT_ID`, `BRAINYCAT_OIDC_ISSUER`, etc.

### API Key Management
- `GET /api/v1/user/api-key` — view current key
- `POST /api/v1/user/api-key/regenerate` — generate new key
- Used for KOReader sync, Kobo sync, MCP server

### Theme Preference
- `PUT /api/v1/user/theme {theme: 'dark'|'light'|'auto'}`
- Persisted in user preferences JSONB

---

## 9. Export & Integration

### Obsidian Export
- `GET /api/v1/export/obsidian` — ZIP of Markdown files
- One `.md` per book with blockquote highlights and bullet-list clippings
- Ready for drag-and-drop into Obsidian vault

### Backup
- `POST /api/v1/backup` — asyncpg COPY → gzipped CSV of all tables

### Readarr Integration
- `POST /api/v1/readarr/search {query}` — search Readarr catalog
- Config: `BRAINYCAT_READARR_URL` + `BRAINYCAT_READARR_API_KEY`

### Book Comparison
- `GET /api/v1/books/compare?a={id}&b={id}`
- Side-by-side metadata + shared tags

---

## 10. Content Processing

### OCR Pipeline
- Auto-submits scanned PDFs to Intello, biggest-first
- Health check before submission (`/api/health`)
- Language validation against `/api/v1/ocr/capabilities`
- PDF chunking for files >30MB
- Hybrid output (text layer + searchable PDF)

### Format Conversion
- EPUB ↔ PDF ↔ MOBI via ebook-convert-rs (Rust) → Calibre → WeasyPrint fallback chain
- MOBI → EPUB auto-conversion on first reader open

### Content Fingerprinting
- **Winnowing:** Full content fingerprinting for cross-format dedup
- **SimHash:** 64-bit hash from first 1000 words (quick upload check)
- **TextProfileSignature:** Apache Nutch-style fuzzy hash (token frequency quantization)
- **MinHash LSH:** datasketch library for corpus-scale O(1) nearest-neighbor lookup

### Duplicate Detection
- Content fingerprinting (winnowing) for cross-format matching
- ISBN-based duplicate detection
- Title similarity (pg_trgm)
- Duplicate page detection in PDFs (pixel hash per page)

---

## 11. Experimental Features

All disabled by default. Enable via environment variables.

| Feature | Config Flag | Endpoint |
|---|---|---|
| TextProfileSignature | `BRAINYCAT_EXP_TEXT_PROFILE=1` | `POST /evaluate/text_profile` |
| MinHash LSH dedup | `BRAINYCAT_EXP_LSH_DEDUP=1` | `POST /evaluate/lsh_dedup` |
| ISBN lookup eval | `BRAINYCAT_EXP_ISBNTOOLS=1` | `POST /evaluate/isbntools` |
| eKitaab file rename | `BRAINYCAT_EXP_FILE_RENAME=1` | `POST /evaluate/file_rename` |
| Kindle EPUB fix | `BRAINYCAT_EXP_KINDLE_FIX=1` | `POST /evaluate/kindle_fix` |
| Reading heatmap | `BRAINYCAT_EXP_HEATMAP=1` | `GET /experimental/heatmap` |
| AI mind maps | `BRAINYCAT_EXP_MIND_MAP=1` | `POST /experimental/mind-map/{id}` |
| Share cards | `BRAINYCAT_EXP_SHARE_CARDS=1` | `POST /experimental/share-card` |
| PDF embed annotations | `BRAINYCAT_EXP_PDF_EMBED=1` | `POST /experimental/pdf-embed/{id}` |
| Duplicate page detection | `BRAINYCAT_EXP_DUPE_PAGES=1` | `POST /evaluate/dupe_pages` |

---

## 12. Infrastructure

### Deployment
```bash
git clone https://github.com/collaed/BrainyCat.git
cd BrainyCat && cp .env.example .env
docker compose -f docker-compose.standalone.yml up -d
# → http://localhost:8000 → Setup wizard
```

### Health Check
- `GET /health` — consolidated status of all subsystems
- Checks: database (book count), Intello (reachable), disk (free GB)
- Returns: `{status: "ok"|"degraded", checks: {...}}`

### Architecture
```
brainycat/
├── web.py              (app wiring, middleware)
├── routes/
│   ├── books.py        (CRUD, bulk ops, covers, compare)
│   ├── admin.py        (stats, jobs, imports, backup, activity)
│   ├── enrichment.py   (intelligence, ISBN, fingerprints)
│   ├── catalog.py      (15 free sources, web search)
│   ├── social.py       (social, clubs, feeds)
│   ├── reader.py       (progress, annotations, goals, collections, lending)
│   ├── media.py        (TTS, conversion, podcast feed)
│   ├── ai.py           (ask, recap, explain, translate)
│   ├── auth.py         (login, OAuth, settings, API keys, theme)
│   ├── kosync.py       (KOReader position + annotation sync)
│   ├── kobo.py         (Kobo e-reader sync)
│   ├── ws.py           (WebSocket real-time updates)
│   └── health.py       (system health check)
├── scheduler.py        (5 supervised loops with crash recovery)
├── metadata.py         (32-source enrichment with merge)
├── isbn.py             (6-method ISBN extraction)
├── recommendations.py  (tag-based similarity + personalized)
├── goodreads_import.py (CSV import with status mapping)
├── kindle_clippings.py (My Clippings.txt parser)
├── calibre_import.py   (reads Calibre metadata.db)
├── smart_merge.py      (duplicate detection + consolidation)
├── obsidian_export.py  (Markdown vault ZIP export)
├── oauth.py            (Google + generic OIDC)
├── experimental/       (10 evaluable features)
└── 50+ more modules
```

### Background Processing
- **5 supervised loops:** enrichment, fingerprinting, title_cleanup (+ series detection), OCR, file watcher
- **Concurrency control:** asyncio.Semaphore(2) for heavy ops
- **Connection pool:** min=3, max=20, 30s statement timeout
- **WebSocket broadcast:** Enrichment events pushed to all connected clients in real-time

### Database
- PostgreSQL 16 with pg_trgm (fuzzy text search) and pgvector (embeddings)
- GIN index on extra_metadata JSONB
- Full-text search via websearch_to_tsquery

---

## 13. UI Features

### Header
- Two-row layout: 🐱 BrainyCat logo + nav (Library, Discover, Intel, Shelves, Settings)
- Active filter indicator + live book count + OPDS link

### Camera ISBN Scanner
- 📷 button in header
- Opens phone camera via getUserMedia
- Uses BarcodeDetector API for real-time EAN-13/EAN-8 detection
- Searches library on successful scan

### Reader Toolbar
- Themes (dark/light/sepia/night)
- Font selector (including OpenDyslexic)
- Bionic Reading toggle
- In-book search
- Dictionary lookup
- Stylus pen/highlighter tools

---

## Configuration

All settings via environment variables (`.env` file):

```env
# Core
DATABASE_URL=postgresql://brainycat:pass@localhost/brainycat
BRAINYCAT_SECRET_KEY=auto-generated-on-first-run

# Intello (AI features)
BRAINYCAT_INTELLO_URL=http://intello:8000

# Google Books (higher quota)
BRAINYCAT_GOOGLE_BOOKS_API_KEY=your-key

# OAuth
BRAINYCAT_GOOGLE_CLIENT_ID=
BRAINYCAT_GOOGLE_CLIENT_SECRET=
BRAINYCAT_OIDC_ISSUER=https://keycloak.example.com/realms/main
BRAINYCAT_OIDC_CLIENT_ID=
BRAINYCAT_OIDC_CLIENT_SECRET=

# Integrations
BRAINYCAT_READARR_URL=http://readarr:8787
BRAINYCAT_READARR_API_KEY=

# Experimental (set to "1" to enable)
BRAINYCAT_EXP_TEXT_PROFILE=0
BRAINYCAT_EXP_LSH_DEDUP=0
BRAINYCAT_EXP_HEATMAP=0
BRAINYCAT_EXP_MIND_MAP=0
BRAINYCAT_EXP_SHARE_CARDS=0
BRAINYCAT_EXP_PDF_EMBED=0
```

---

## License

AGPL-3.0
