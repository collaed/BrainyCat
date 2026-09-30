# Reader

## Supported Formats

| Format | Renderer | Notes |
|--------|----------|-------|
| EPUB | epub.js | Primary format, smooth scroll, full features |
| PDF | pdf.js | Lazy page rendering, progress tracking |
| MOBI/AZW3/KFX | Convert → EPUB | Auto-converted on first open via ebook-convert |
| CBZ/CBR | Image viewer | Comic/manga reader |
| TXT/MD/HTML | Wrapped EPUB | Converted to minimal EPUB for consistent reading |

## EPUB Reader (`/static/reader.html`)

60KB of vanilla JavaScript. No React, no framework.

### Features

- **Smooth scrolling** (no pagination flicker)
- **4 themes:** light, dark, sepia, night
- **Font selection:** system fonts + OpenDyslexic
- **Font size / line height / margin** adjustable
- **Progress tracking:** server-sync on chapter change and every 60s
- **Dictionary:** tap word → definition (language-aware, tries book language first)
- **Text selection → actions:** highlight, copy, explain (LLM), translate
- **Clippings:** saved highlights with export to Markdown (Obsidian format)
- **Custom CSS injection:** user stylesheets for accessibility

### Stylus Annotations

Pressure-sensitive pen/highlighter overlay for e-ink tablets (Boox, Remarkable, iPad):
- Pen mode (thin, pressure-varies-width)
- Highlighter mode (thick, semi-transparent)
- Eraser mode
- Color picker
- Synced to server (stored in `annotations` table)

### Progress Sync

```
reader.html → POST /api/v1/progress/{book_id}
            → {chapter_index, position, percentage, timestamp}
            → stored in reading_progress table
            → synced to KOReader via kosync protocol
```

Conflict resolution: latest timestamp wins.

## PDF Reader

Uses pdf.js with:
- Lazy page rendering (only renders visible pages + 2 ahead)
- Progress tracking (page number / total pages → percentage)
- In-app viewing (no separate tab)
- Zoom controls

## Format Conversion

Chain: ebook-convert-rs (Rust, fast) → Calibre `ebook-convert` (reliable) → WeasyPrint (PDF output)

Conversion happens:
1. On first open (if format not directly renderable)
2. On explicit "Convert to EPUB/PDF" action
3. On Kindle delivery (target format: MOBI or EPUB depending on device)

Converted files are cached as additional `book_files` entries.

## Device Sync

### KOReader

Full kosync protocol implementation:
- `PUT /api/v1/kosync/progress` → update position
- `GET /api/v1/kosync/progress` → get position
- Auth via device ID + password

KOReader file matching uses `koreader_hash.py` — partial MD5 (first 4KB + file size) to identify books regardless of path.

### ABS Mobile (AudiobookShelf)

Login + browse + play compatibility:
- OAuth-style login flow
- Library browsing API
- Audio streaming with chapter navigation
- Position sync

### OPDS Feed

`/opds/` and `/opds/feed.xml` — compatible with Moon+ Reader, KOReader, Calibre:
- Catalog feed (list all books)
- Search feed
- Acquisition links (download files)

## Audio Player (`/static/player.html`)

- Chapter navigation (from `audio_chapters` table)
- Speed control (0.5x - 3x)
- Sleep timer (15m, 30m, 45m, 1h, end of chapter)
- Media Session API (lockscreen controls)
- Position sync to server

### Chapter Merge

Multiple MP3 files → single M4B with chapter markers:
```
ffmpeg -i concat:01.mp3|02.mp3|... -c:a aac -b:a 64k -ac 1 output.m4b
```
Mono, 64kbps AAC, speech-optimized. Chapter markers computed from individual file durations.

## TTS (Text-to-Speech)

Two paths:
1. **Piper (local):** Offline, fast, runs in container. Quality: acceptable for non-fiction.
2. **Groq/Voxtral (via Intello):** Higher quality, requires Intello connectivity.

EPUB → chapter text extraction → TTS → MP3 files → merged M4B.

## File Structure

```
static/
├── reader.html       (60KB — EPUB reader, epub.js)
├── player.html       (18KB — audio player)
├── catalog.html      (9KB — free catalog browser)
├── index.html        (18KB — main library UI)
├── intelligence.html (12KB — enrichment dashboard)
├── verify.html       (6KB — confidence verification UI)
└── ...
```

All vanilla HTML/JS. No build step. No TypeScript. No bundler.
