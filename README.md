# 🐱 BrainyCat

Self-hosted unified personal library for ebooks and audiobooks.

## Features

- **Library Management** — Upload, organize, browse ebooks (EPUB/PDF/MOBI) and audiobooks (MP3/M4B/FLAC)
- **Bulk Operations** — Multi-select books for batch tagging, enrichment, deletion, conversion
- **EPUB Reader** — In-browser reader with progress tracking, bookmarks, annotations, themes, genre-coded margins
- **PDF Reader** — In-browser PDF viewing with pdf.js, progress tracking, lazy page rendering
- **MOBI/AZW3 Reading** — Auto-converts to EPUB on first open
- **Audio Player** — Chapter navigation, speed control, sleep timer, Media Session API
- **Metadata Enrichment** — Auto-fetch from Google Books, Open Library, Gutendex, Wikidata
- **ISBN Barcode Scanner** — pyzbar decodes EAN-13 barcodes from scanned PDF back covers
- **Multi-ISBN Extraction** — Stores print, ebook, PDF, audiobook ISBNs with type detection
- **Edition Detection** — Multilingual (English/French/German/Spanish) edition number extraction
- **Original Title Detection** — Extracts original title from translations
- **Cover Generation** — Genre-styled covers (fiction: vertical stripe, non-fiction: horizontal stripe)
- **Library Intelligence** — Quality analysis, series detection, author dedup, duplicate detection
- **Quality Score** — Calibre-aligned 10-field weighted scoring (100 max)
- **Language Detection** — From EPUB OPF metadata + ISBN region inference
- **Missing Data Filter** — Filter library by missing ISBN, description, cover, tags, quality
- **Text-to-Speech** — Piper TTS converts ebooks to per-chapter audiobooks
- **Speech-to-Text** — Via Intello (Groq Whisper) with chapter splitting
- **Format Conversion** — EPUB → PDF via WeasyPrint
- **Translation** — Pluggable backends: Argos (local), DeepL, Google, LLM, Ollama
- **Bilingual Reader** — Side-by-side reader (in development)
- **Reading/Listening Sync** — Position tracking (sync map generation in development)
- **Kindle Delivery** — Send books via email to Kindle devices
- **Public Domain Catalog** — Browse/import from Project Gutenberg + LibriVox
- **Recommendations** — Taste profile with DNA match, author favorites, series completion
- **AI Companion** — Recap, Q&A, character tracker, auto-tagging via LLM
- **Audio Restoration** — Diagnose and clean vinyl crackle, tape hiss, hum, clipping
- **OPDS Feed** — Compatible with Moon+ Reader, KOReader, Calibre
- **Podcast Feeds** — Drip-schedule audiobook chapters as RSS
- **Reading Statistics** — Books/month, genre distribution, streaks
- **Multi-User** — Shared files, per-user progress/shelves/preferences
- **Signal Notifications** — New books, job completions
- **CLI Tool** — `brainycat upload`, `search`, `send-to-kindle`, `stats`

## Library Stats

📚 **1,551 books** — 97.1% ISBN · 94.3% language · 99.8% covers · 60% descriptions

## Tech Stack

**Backend:** Python 3.12, FastAPI, asyncpg, PostgreSQL 16 (pg_trgm, pgvector-ready)
**Frontend:** Vanilla HTML/JS/CSS, EPUB.js, Chart.js
**Audio:** Piper TTS, faster-whisper, ffmpeg, SoX
**Ebook:** ebooklib, PyMuPDF, WeasyPrint
**Deploy:** Docker, Caddy reverse proxy

## Quick Start

```bash
cp .env.example .env  # Edit with your settings
docker compose up -d
# → http://localhost:8000
```

## Genre Color Coding

BrainyCat uses a visual color system in book covers and reader margins:

**Fiction** (vertical stripe):
- 🔵 General fiction · 🔴 Romance · ⚫ Thriller · 🟣 Fantasy
- 🔵 Sci-fi · 🟤 Mystery · 🟢 Literary · 🔴 Erotica

**Non-fiction** (horizontal stripe):
- 🔴 General · 🟡 Self-help · 🔵 Business · 🟢 Science
- 🟤 History · 🟣 Philosophy · 🔵 Psychology · ⚫ Technology

## License

Private project.
