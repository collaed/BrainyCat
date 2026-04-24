# 🐱 BrainyCat

**Self-hosted personal library with automatic metadata enrichment, web reader, and audiobook player.**

Upload your ebooks and audiobooks. BrainyCat enriches them from 32 metadata sources, organizes them, and lets you read in the browser — with progress sync, annotations, and stylus support.

## Quick Start

```bash
git clone https://github.com/collaed/BrainyCat.git
cd BrainyCat
cp .env.example .env
docker compose -f docker-compose.standalone.yml up -d
# → http://localhost:8000 → Setup wizard creates your admin account
```

Includes PostgreSQL with pgvector. No external dependencies required.

**With existing PostgreSQL:**
```bash
# Edit .env with your DATABASE_URL
docker compose up -d
```

**With Intello (AI features):**
Set `BRAINYCAT_INTELLO_URL=http://your-intello:8000` in `.env` to enable TTS, STT, OCR, and LLM features. BrainyCat works fully without Intello — AI features degrade gracefully.

## Features

### Library Management
- **22 upload formats** — EPUB, PDF, MOBI, AZW3, KFX, FB2, DOCX, ODT, TXT, RTF, HTML, MD, DJVU, CBZ, CBR + audio (MP3, M4B, FLAC, OGG)
- **Bulk operations** — multi-select for batch tagging, enrichment, deletion, conversion
- **Format conversion** — EPUB ↔ PDF ↔ MOBI via ebook-convert-rs (Rust) → Calibre → WeasyPrint fallback chain
- **Duplicate detection** — content fingerprinting + title similarity (pg_trgm) + ISBN matching
- **Quality score** — Calibre-aligned 10-field weighted scoring (100 max)

### Metadata Enrichment (32 sources, automatic)
- **Global** — Google Books, Open Library (Works API + Ratings), Gutendex, Library of Congress, WorldCat, VIAF, ISNI
- **Regional** — BnF 🇫🇷, DNB 🇩🇪, BNE 🇪🇸, British Library 🇬🇧, Rakuten 🇯🇵, NDL 🇯🇵, Douban 🇨🇳
- **Social** — StoryGraph, Hardcover, Babelio, Skoob, ComicVine, MyAnimeList
- **Commercial** — Amazon (12 countries), Edelweiss, Thalia, BOL.com, Casa del Libro
- **Covers** — Google Images, Apple Books, Bookcover API
- **Smart routing** — ISBN region detection routes French books to BnF first, German to DNB, etc.
- **BISAC/Thema codes** — auto-mapped from tags, LLM verification for edge cases

### ISBN Intelligence
- **6 extraction methods** — OPF metadata, full-text scan, barcode decode (pyzbar), filename, title, check-digit completion
- **Multi-ISBN storage** — print, ebook, PDF, audiobook ISBNs with type detection
- **Unicode dash handling** — `978‐1‐118‐99094‐0` (U+2010) → `9781118990940`
- **285 registration groups** — official ISBN Range Message for region/language detection

### Reading
- **EPUB reader** — epub.js with smooth scrolling, progress tracking, themes (dark/light/sepia/night), font selector (including OpenDyslexic)
- **PDF reader** — pdf.js with lazy page rendering, progress tracking, in-app viewing
- **MOBI/AZW3** — auto-converts to EPUB on first open
- **Stylus annotations** — pressure-sensitive pen/highlighter overlay, works on Boox/Remarkable/iPad, synced across devices
- **Dictionary** — tap a word for definition (language-aware, tries book language first)
- **Clippings** — highlight text → save/explain (LLM)/translate, export to Markdown (Obsidian-compatible)
- **Custom CSS injection** — user stylesheets for accessibility (OpenDyslexic, high contrast, custom line-height)

### Audio
- **Player** — chapter navigation, speed control, sleep timer, Media Session API
- **Chapter merge** — multiple MP3s → single M4B with chapter markers (AAC 64k mono, speech-optimized)
- **TTS** — Piper (local) + Groq/Voxtral (via Intello) for ebook → audiobook conversion
- **STT** — Groq Whisper for audiobook → text transcription

### Discovery
- **15 free catalog sources** — Gutenberg, Standard Ebooks, LibriVox, Internet Archive, Feedbooks, OAPEN, arXiv, Semantic Scholar, CORE, Unpaywall, DOAB, Loyal Books, ManyBooks, GitHub, OpenStax
- **OPDS subscriptions** — 8 pre-configured catalogs (75,000+ free books), add custom OPDS feeds
- **One-click import** — search any catalog → import directly to library (server-side download)
- **Taste engine** — 7-category Book Genome (DNA, Author, Community, Hidden Gems, Series, Anti, NLP themes)

### Social & Sync
- **Federated profiles** — cross-instance following, 3-layer privacy
- **Book clubs** — pace-locked chapters, spoiler-safe discussions
- **Reading goals** — "50 books in 2026" with progress tracking
- **OPDS feed** — compatible with Moon+ Reader, KOReader, Calibre
- **KOReader sync** — position tracking
- **ABS mobile app** — full playback compatibility (login, browse, play, sync)
- **Kindle delivery** — send books via email
- **MCP server** — 28 AI tools for integration with Claude, GPT, etc.

### Background Processing
- **Supervised scheduler** — 4 loops with crash recovery, row locking, timeouts
- **Enrichment** — 3 books/minute with adaptive rate limiting (fail2ban-style)
- **OCR pipeline** — auto-submits scanned PDFs to Intello, polls results, splits large PDFs into chunks
- **Genre classification** — Google Books categories → BISAC/Thema codes, LLM fallback
- **Title cleanup** — ISBN extraction, dirty title fixing, barcode scanning

## Library Stats

📚 **1,528 books** — 80% ISBN · 94% language · 99.9% covers · 61% descriptions · 46% pubdate · 67.9 avg quality

## Architecture

```
brainycat/
├── web.py              (139 lines — app wiring only)
├── routes/
│   ├── books.py        (1,483 — CRUD, bulk ops, covers)
│   ├── admin.py        (771 — stats, jobs, imports, backup)
│   ├── enrichment.py   (700 — intelligence, ISBN, fingerprints)
│   ├── catalog.py      (580 — 15 free catalog sources)
│   ├── social.py       (328 — social, clubs, feeds)
│   ├── reader.py       (330 — progress, annotations, pen, OPDS)
│   ├── media.py        (113 — TTS, conversion, EPUB tools)
│   ├── ai.py           (100 — companion, explain, translate)
│   └── auth.py         (91 — login, users, settings)
├── scheduler.py        (supervised background tasks)
├── metadata.py         (32-source enrichment with merge)
├── isbn.py             (6-method ISBN extraction)
├── bisac.py            (BISAC/Thema mapping + LLM)
├── ocr_optimize.py     (strip text-images, keep illustrations)
└── 100+ more modules
```

**Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL 16 (pg_trgm, pgvector), vanilla HTML/JS, Docker

## MCP Integration

BrainyCat exposes 28 tools via the Model Context Protocol for AI assistant integration.

**Setup:**
```bash
# In your MCP client config (Claude Desktop, etc.)
{
  "mcpServers": {
    "brainycat": {
      "command": "python",
      "args": ["-m", "brainycat.mcp_server"],
      "env": {
        "BRAINYCAT_URL": "http://localhost:8000",
        "BRAINYCAT_API_KEY": "your-api-key"
      }
    }
  }
}
```

**Example conversation with Claude:**

```
User: What books do I have about diving?

Claude: [calls search_books(query="diving")]
You have 4 diving books:
1. Plongée Plaisir - Niveau 2 (PDF, French)
2. Plongée Plaisir - Niveau 3 (PDF, French)
3. Scuba Diving - Monty Halls (PDF, English)
4. Freedive! (PDF, English)

User: Enrich the Monty Halls one and find similar books.

Claude: [calls enrich_book(book_id="740f7f0b-...")]
Enriched from 3 sources: Google Books, Open Library, Amazon UK.
Added: ISBN 9780756619497, publisher DK, 346 pages.

[calls similar_books(book_id="740f7f0b-...")]
Similar books in your library:
- Plongée Plaisir N2 (92% match — same genre, diving)
- Le manuel du vol libre (71% — outdoor sports)

User: Convert the Freedive book to EPUB and send it to my Kindle.

Claude: [calls convert_format(book_id="...", target_format="epub")]
Converted to EPUB (2.1 MB).

[calls send_to_kindle(book_id="...")]
Sent to your Kindle (user@kindle.com).
```

**Available tools:** search_books, get_book, edit_book, delete_book, similar_books, enrich_book, batch_enrich, classify_book, search_content, recap, ask_book, library_stats, efficiency, book_sources, send_to_kindle, convert_tts, convert_format, merge_authors, create_series, taste_recommendations, epub_check, epub_lint, count_pages

## Genre Color Coding

BrainyCat uses a visual color system in book covers and reader margins:

**Fiction** (vertical stripe): 🔵 General · 🔴 Romance · ⚫ Thriller · 🟣 Fantasy · 🔵 Sci-fi · 🟤 Mystery · 🟢 Literary · 🔴 Erotica

**Non-fiction** (horizontal stripe): 🔴 General · 🟡 Self-help · 🔵 Business · 🟢 Science · 🟤 History · 🟣 Philosophy · 🔵 Psychology · ⚫ Technology

## Data Persistence

| Data | Location | Backup |
|---|---|---|
| Books, metadata, progress | PostgreSQL (`brainycat-pgdata` volume) | `POST /api/v1/backup` → gzipped CSV |
| Book files, covers, OCR results | `/data/books/` (`brainycat-data` volume) | File-level backup |
| User settings, API keys | PostgreSQL | Included in DB backup |

## License

AGPL-3.0 — see [LICENSE](LICENSE)
