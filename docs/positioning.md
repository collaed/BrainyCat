# BrainyCat vs Calibre — Positioning Document

## What Calibre Is

Calibre is a **desktop e-book manager** — a single-user application you install on your PC. Its tagline: *"an e-book manager that can view, convert, edit and catalog e-books in all of the major e-book formats."* It's been developed for 15+ years by Kovid Goyal and hundreds of contributors, with 3 million active installs.

Calibre's core promise: **"You're never more than three clicks away from your goal."**

## What BrainyCat Is

BrainyCat is a **self-hosted web library for ebooks and audiobooks** — a multi-user server application you deploy once and access from any browser. It was built in 2 days as a unified platform for written and spoken content.

BrainyCat's core promise: **"Your one-stop shop for everything you read and listen to, enriched automatically."**

## They Solve Different Problems

| Dimension | Calibre | BrainyCat |
|---|---|---|
| **Deployment** | Desktop install (Windows/Mac/Linux) | Docker container, one command |
| **Users** | Single user | Multi-user (shared files, per-user progress) |
| **Access** | Local machine only (or content server) | Any browser, anywhere, behind auth |
| **Audio** | None | Full audiobook support (player, TTS, STT, restoration) |
| **AI** | None | LLM classification, AI companion, auto-tagging |
| **Enrichment** | Manual "Download metadata" button | Continuous background enrichment (7 sources) |
| **Translation** | None | 5 backends + bilingual reader |
| **OCR** | None | Via Intello (searchable PDF with images) |
| **Format conversion** | 40+ formats (their crown jewel) | EPUB→PDF only (WeasyPrint) |
| **Book editing** | Full IDE | Metadata editor only |
| **Device support** | 30+ physical devices | Kindle email + OPDS |

## Requirements BrainyCat Addresses

### R1: Unified Library for Text and Audio
- Upload and manage ebooks (EPUB, PDF, MOBI) and audiobooks (MP3, M4B, FLAC) in one place
- Convert between them: ebook→audiobook (Piper TTS), audiobook→ebook (Whisper STT)
- Sync reading/listening position across formats

### R2: Automatic Metadata Intelligence
- Extract ISBN from OPF metadata and text content (10 languages, EU legal compliance)
- Enrich from 7 sources: Google Books, Open Library, Library of Congress, Amazon, Gutendex, Hardcover, Wikidata
- Calibre-style merge: shortest title, longest description, averaged ratings
- LLM-based Thema genre classification for books not in any database
- Background enrichment: continuous, no manual intervention

### R3: Content-Based Duplicate Detection
- Winnowing algorithm (k-gram rolling hashes) for text fingerprinting
- Structural fingerprinting (chapter skeleton)
- MinHash for fast Jaccard similarity estimation
- Front matter edition detection (number line, edition statements)
- Series vs duplicate disambiguation

### R4: Multi-User Web Access
- Caddy forward_auth integration (X-Auth-User header)
- Session-based login with bcrypt
- OAuth stubs (Google, GitHub)
- Per-user: reading progress, bookmarks, annotations, collections, preferences

### R5: In-Browser Reading and Listening
- EPUB.js reader with progress tracking, bookmarks, themes, genre-coded margins
- Audio player with chapter navigation, speed control, sleep timer, Media Session API
- Bilingual side-by-side reader with synchronized scrolling

### R6: Public Domain Catalog
- Browse/search/import from Project Gutenberg (60,000+ ebooks)
- Browse/search/import from LibriVox (15,000+ audiobooks)
- One-click import with automatic metadata

### R7: Library Intelligence
- Author deduplication ("First Last" ↔ "Last, First")
- Series detection from external sources (Google Books, Amazon) and local patterns
- Quality analysis (bitrate, chapters, file integrity)
- Content duplicate detection with confidence scores
- Enrichment activity tracking per source per time period

### R8: Audio Processing
- Text-to-speech via Piper (per-chapter MP3s)
- Speech-to-text via Whisper (with chapter splitting)
- Audio restoration (vinyl, tape, hum, clipping profiles)
- OCR for scanned PDFs (via Intello, page-by-page or job-based)

### R9: Delivery and Distribution
- Send to Kindle via email (EPUB or PDF for workbooks)
- OPDS 1.2 feed for external reader apps
- Podcast RSS feeds (drip-scheduled audiobook chapters)
- Recently added Atom feed

### R10: Cover Management
- Extract from EPUB metadata and PDF first pages
- Download from Google Books
- Generate genre-styled covers (fiction: vertical stripe, non-fiction: horizontal stripe)
- Optimize oversized covers (saved 121MB on 633 covers)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser / CLI                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    Caddy Reverse Proxy                        │
│              forward_auth → auth:8080                         │
│              tools.ecb.pm/brainycat/*                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ X-Auth-User header
┌──────────────────────────▼──────────────────────────────────┐
│                   BrainyCat (FastAPI)                         │
│                                                              │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────────┐ │
│  │ Library CRUD │ │ EPUB.js      │ │ Background Scheduler  │ │
│  │ Upload/Search│ │ Audio Player │ │ · ISBN extraction      │ │
│  │ Collections  │ │ Bilingual    │ │ · Metadata enrichment  │ │
│  │ Book Links   │ │              │ │ · Fingerprinting       │ │
│  └──────┬───────┘ └──────────────┘ │ · Duplicate detection  │ │
│         │                          └───────────┬─────────────┘ │
│  ┌──────▼───────┐ ┌──────────────┐ ┌──────────▼─────────────┐ │
│  │ Intelligence │ │ Covers       │ │ Metadata Sources (7)   │ │
│  │ · Authors    │ │ · Extract    │ │ · Google Books         │ │
│  │ · Series     │ │ · Generate   │ │ · Open Library         │ │
│  │ · Duplicates │ │ · Optimize   │ │ · Library of Congress  │ │
│  │ · Quality    │ │              │ │ · Amazon (via Google)  │ │
│  └──────────────┘ └──────────────┘ │ · Gutendex             │ │
│                                    │ · Wikidata             │ │
│  ┌──────────────┐ ┌──────────────┐ │ · LLM (Intello)       │ │
│  │ ISBN Extract  │ │ Fingerprints │ └────────────────────────┘ │
│  │ · OPF Dublin  │ │ · Winnowing  │                            │
│  │ · Text scan   │ │ · MinHash    │                            │
│  │ · 10 languages│ │ · Structural │                            │
│  └──────────────┘ └──────────────┘                            │
└──────────┬──────────────┬──────────────┬──────────────────────┘
           │              │              │
    ┌──────▼──────┐ ┌─────▼─────┐ ┌─────▼──────┐
    │ PostgreSQL  │ │ Intello   │ │ Mailserver │
    │ 16 + pg_trgm│ │ TTS/STT   │ │ SMTP       │
    │ 33 tables   │ │ OCR       │ │ Kindle     │
    │ tsvector FTS│ │ LLM (13)  │ │            │
    └─────────────┘ └───────────┘ └────────────┘
```

## User Journeys

### Journey 1: "I have 2000 ebooks scattered across folders"
1. Click "📁 Upload Folder" → select directory
2. BrainyCat recursively finds all supported files, skips duplicates
3. Extracts metadata from each file (OPF, PDF, audio tags)
4. Background: extracts ISBNs, enriches from 7 sources, generates covers
5. Within hours: full library with covers, descriptions, genres, series

### Journey 2: "I want to listen to this ebook"
1. Open book → click "🔊 TTS"
2. Piper TTS generates one MP3 per chapter
3. Open audio player → chapters listed, speed control, sleep timer
4. Switch between reading and listening at matching positions

### Journey 3: "I want to learn French with this book"
1. Open book → click "🌐 Translate" → select French→English
2. Translation runs paragraph by paragraph
3. Open "🌐 Bilingual" → side-by-side original + translation
4. Click any word for instant translation

### Journey 4: "Clean up my messy library"
1. Intelligence page → Author Cleanup: merge "J.R.R. Tolkien" with "Tolkien, J.R.R."
2. Series Detection: auto-detected from Google Books subtitles
3. Content Duplicates: winnowing fingerprints find same book in different editions
4. Quality Issues: low bitrate audio, missing chapters flagged

### Journey 5: "Send this technical book to my Kindle"
1. Mark book as "Workbook" in editor
2. Click "📱 Kindle" → sends PDF (not EPUB) for layout preservation
3. Book arrives on Kindle with annotations enabled

## What We Don't Do (And Why)

| Feature | Why Not |
|---|---|
| 40+ format conversion | 15 years of reverse engineering. We do EPUB→PDF via WeasyPrint. |
| Book editing IDE | We're a library, not an editor. Use Sigil or Calibre for that. |
| Physical device drivers | USB/MTP is a desktop concern. We deliver via email and OPDS. |
| CSS polishing | We serve books as-is. The reader handles rendering. |
| Template language | Web apps use APIs, not template expressions. |
| News download | RSS readers exist. We focus on books. |

## Tech Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, PostgreSQL 16
- **Frontend**: Vanilla HTML/JS/CSS, EPUB.js, Chart.js
- **Audio**: Piper TTS, faster-whisper, ffmpeg, SoX
- **Ebook**: ebooklib, PyMuPDF, WeasyPrint
- **AI**: Intello (13 LLM providers), Thema classification
- **Quality**: ruff, mypy, pytest, alembic migrations
- **Deploy**: Docker, Caddy reverse proxy
