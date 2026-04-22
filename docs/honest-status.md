# BrainyCat — Honest Status

## What Works (Verified)

| Feature | Status | Details |
|---|---|---|
| Library management | ✅ Solid | Upload, search (ILIKE + tsvector + pg_trgm), collections, book linking |
| EPUB reader | ✅ Works | epub.js with progress, themes, genre margins, TOC |
| Audio player | ✅ Works | Chapter navigation, speed control, sleep timer, Media Session |
| TTS (ebook→audio) | ✅ Works | Piper neural TTS + espeak-ng fallback, per-chapter MP3s |
| Metadata enrichment | ✅ Works | 5 active sources (Google Books, Open Library, LoC, Amazon, Gutendex), background |
| ISBN extraction | ✅ Works | OPF + text scan, 9 language groups, EU legal anchors |
| Content fingerprinting | ✅ Works | Winnowing + MinHash + structural, 346 books done |
| Author deduplication | ✅ Works | Normalized matching, "First Last" ↔ "Last, First" |
| Series detection | ✅ Works | From Google Books subtitles + local title patterns |
| Cover generation | ✅ Works | Genre-styled covers, optimization (saved 121MB) |
| Audio restoration | ✅ Works | 7 ffmpeg profiles (vinyl, tape, hum, declip) |
| LLM classification | ✅ Works | Thema codes from text samples via Intello |
| Multi-user auth | ✅ Works | Caddy forward_auth + session cookies, 2 roles |
| EPUB→PDF conversion | ✅ Works | WeasyPrint with CSS rendering |
| Kindle delivery | ✅ Works | SMTP via mailserver, respects workbook flag |
| OPDS feed | ✅ Basic | Last 100 books, search, no pagination/facets |
| Reading statistics | ✅ Works | Genre distribution, top authors, personality analysis |
| Background scheduler | ✅ Works | ISBN extraction + enrichment + fingerprinting |

## What's a Stub or Incomplete

| Feature | Status | Reality |
|---|---|---|
| Bilingual reader | ⚠️ Stub | UI shell exists, no content loading from translations |
| Text↔audio sync | ⚠️ Stub | DB schema + position translation code, but nothing generates sync maps |
| STT (audio→text) | ⚠️ Delegated | Requires Intello's Groq Whisper. Local faster-whisper not in Docker |
| OCR | ⚠️ Delegated | 100% Intello dependency. No local capability |
| Recommendations | ⚠️ Basic | Simple frequency counting. pgvector unused (postgres image not swapped) |
| MOBI metadata | ⚠️ Missing | Accepts uploads but can't read MOBI metadata |
| Podcast feeds | ⚠️ Minimal | Creates RSS but untested with real podcast apps |

## What We Claimed But Don't Have

| Claim | Reality |
|---|---|
| "EPUB ↔ MOBI/AZW3 conversion" | Only EPUB→PDF. No MOBI/AZW3 conversion at all |
| "7 metadata sources" | 5 active. OCLC decommissioned, Hardcover Cloudflare-blocked |
| "DNA match recommendations" | Simple tag counting, not ML/embeddings |
| "faster-whisper local fallback" | Not in Docker image or requirements |

## What Calibre Has That We Incorrectly Claimed They Don't

| Our Claim | Calibre Reality |
|---|---|
| "Web reader: None" | 42-file reader with annotations, TTS, SMIL, offline |
| "Multi-user: Single user" | Per-user restrictions, read-only mode, auth |
| "Audio: None" | Piper TTS, speechd, Qt TTS, SMIL overlays, read-aloud |
| "Background enrichment: Manual" | Bulk download, auto after import, parallel |
| "ISBN extraction: Manual" | Auto from OPF, FB2, ODT, CHM, audio tags |
| "Desktop only" | calibre-server is a headless daemon with SSL/OPDS |

## Honest Comparison

| Feature | Calibre | BrainyCat | Winner |
|---|---|---|---|
| Format conversion | 20+ any-to-any | EPUB→PDF only | **Calibre** |
| Book editing | Full IDE | None | **Calibre** |
| Device drivers | 30+ physical | Kindle email | **Calibre** |
| Web reader | 42-file, annotations, TTS | epub.js + themes | **Calibre** |
| Multi-user | Per-user restrictions | 2 roles, per-user progress | **Calibre** |
| Plugin ecosystem | Hundreds of community plugins | Fixed source modules | **Calibre** |
| Template language | Turing-complete | None | **Calibre** |
| Custom columns | Unlimited | Fixed schema | **Calibre** |
| Quality checker | 7-module linter | None | **Calibre** |
| Test coverage | ~47 test points | 4 test files | **Calibre** |
| Maturity | 700K lines, 15 years | 7K lines, 2 days | **Calibre** |
| Content fingerprinting | None | Winnowing + MinHash | **BrainyCat** |
| ISBN text extraction depth | OPF/FB2/tags | OPF + full text, 9 languages | **BrainyCat** |
| Series auto-detection | None | External + local patterns | **BrainyCat** |
| Author deduplication | None | Normalized matching | **BrainyCat** |
| LLM genre classification | None | Thema from text samples | **BrainyCat** |
| Audio restoration | None | 7 ffmpeg profiles | **BrainyCat** |
| Audiobook management | None | Player, chapters, progress | **BrainyCat** |
| TTS | Piper + speechd + Qt | Piper + espeak + Intello | Tie |
| Translation | None | Argos/LLM (bilingual is stub) | **BrainyCat** (with caveat) |

**Score: Calibre 11, BrainyCat 7, Tie 1.**

## Where BrainyCat Genuinely Adds Value

1. **Intelligence layer**: Fingerprinting, author dedup, series detection, LLM classification — none of this exists in Calibre
2. **Audiobook-first**: Full player, TTS conversion, audio restoration — Calibre treats audio as an afterthought
3. **Continuous enrichment**: Background process that never stops improving your library
4. **Multilingual ISBN extraction**: 9 language groups with EU legal anchors (Achevé d'imprimer, Impressum, Dépôt légal)
5. **Web-native**: No install, works on any device with a browser

## What To Fix Next

1. **Tests**: Get to 50+ meaningful tests
2. **Bilingual reader**: Actually load translated content
3. **Sync maps**: Generate them during STT
4. **MOBI metadata**: Add mutagen/ebooklib MOBI support
5. **OPDS**: Pagination, facets, proper acquisition links
6. **Recommendations**: Use pgvector when postgres image is swapped
7. **README**: Remove claims that don't match code
