# r/selfhosted Post Draft

**Title:** BrainyCat — self-hosted book library with automatic metadata enrichment and web reader

---

**Project Name:** BrainyCat

**Repo/Website Link:** https://github.com/collaed/BrainyCat

**Description:**

Self-hosted personal library that automatically enriches your books with covers, ISBNs, genres, and descriptions from 32 metadata sources. Upload your ebooks and audiobooks, BrainyCat does the rest.

I built this because I had 1,500+ books scattered across formats with terrible metadata — missing covers, no ISBNs, wrong titles. Calibre is great for manual curation but I wanted something that runs continuously in the background and fixes everything automatically.

**Key features:**

- **22 upload formats** — EPUB, PDF, MOBI, AZW3, KFX, FB2, DOCX, CBZ/CBR + audio (MP3, M4B, FLAC)
- **32 enrichment sources** — Google Books, Open Library, BnF, DNB, Amazon (12 countries), StoryGraph, Hardcover, VIAF, and more. Runs automatically in the background.
- **ISBN barcode scanning** — extracts ISBNs from scanned PDF back covers using pyzbar
- **Web reader** — EPUB (epub.js) and PDF (pdf.js) with progress sync, themes, dictionary, stylus annotations
- **Audiobook support** — chapter merge (MP3→M4B), TTS via Piper/Groq, player with sleep timer
- **15 free catalog sources** — browse and one-click import from Gutenberg, Standard Ebooks, LibriVox, arXiv, Internet Archive, and more (75,000+ free books)
- **MCP server** — 28 tools for Claude/GPT integration ("What books do I have about diving?" → search → enrich → convert → send to Kindle)
- **Stylus annotations** — pressure-sensitive pen/highlighter overlay, synced across devices. Works on Boox/Remarkable/iPad.

**What it doesn't do:** It's not a Calibre replacement. It's an intelligence layer. Upload your books (or point it at your Calibre library), and it enriches them continuously.

**Deployment:**

```bash
git clone https://github.com/collaed/BrainyCat.git
cd BrainyCat
cp .env.example .env
docker compose -f docker-compose.standalone.yml up -d
# → http://localhost:8000 → Setup wizard creates your admin account
```

Includes PostgreSQL with pgvector. No external dependencies required. Optional Intello server for AI features (TTS, STT, OCR, LLM) — everything works without it.

**Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL 16, vanilla HTML/JS, Docker

**AI Involvement:** AI was used extensively in development (Claude for implementation, architecture decisions human-directed). The app itself uses LLMs optionally for genre classification, book summaries, and translation — all via a separate Intello server that's not required. Core functionality (enrichment, ISBN extraction, reader, player) is fully deterministic.

**Current state:** Running on my server with 1,528 books. 82% ISBN coverage, 99.9% covers, 63% descriptions — all filled automatically. AGPL-3.0 licensed.

[screenshot: library grid] [screenshot: book detail with enrichment] [screenshot: reader with annotations]
