# BrainyCat — Positioning

## What BrainyCat Is

**The AI reading companion for your book library.**

BrainyCat is an intelligence layer that sits alongside your existing library tools — Calibre, calibre-web, Audiobookshelf, Kavita, or any OPDS server. It doesn't replace them. It makes them smarter.

Calibre owns files, metadata, organization, and conversion.
BrainyCat owns discovery, intelligence, consumption, and social.

## What Makes BrainyCat Unique

These features exist nowhere else in the self-hosted book space:

| Feature | What It Does | Closest Alternative |
|---|---|---|
| Book Genome taste engine | 7-category recommendations from reading history | Nothing (Goodreads is cloud-only) |
| MCP server (28 tools) | AI clients manage your library via natural language | Nothing |
| Content fingerprinting | Winnowing + MinHash detects same book across editions | Calibre Find Duplicates (title only) |
| Smart sleep detection | Behavioral dead-man's-switch for audiobook listeners | Nothing (mobile apps use sensors) |
| Federated reading profiles | Privacy-preserving social across instances | Nothing |
| Contextual footnotes | LLM-generated historical/cultural annotations | Nothing |
| Edition diffing | Paragraph-level diff between book versions | Nothing |
| Readability scoring | Flesch-Kincaid + Gunning Fog + reading time estimates | Calibre Count Pages plugin (partial) |
| ABS mobile app compat | 30K+ existing app users can connect to BrainyCat | Nothing |
| Unified catalog search | 8 sources (120K+ free books) in parallel | Nothing |
| Calibre sync plugin | Two-way enrichment bridge via Calibre's plugin repo | Nothing |
| Book clubs | Pace-locked chapters with spoiler-safe discussions | Nothing self-hosted |
| getAbstract-style summaries | Structured non-fiction summaries via LLM | Nothing |
| 10 enrichment sources | Parallel fetch, Calibre-style merge, cover validation | Calibre (deeper but manual) |

## How BrainyCat Relates to the Ecosystem

### Calibre (desktop, 15+ years, dominant)
- **Relationship**: Companion, not competitor
- **Integration**: Calibre plugin for two-way sync, reads metadata.db, uses ebook-convert
- **Division of labor**: Calibre handles files/formats/editing, BrainyCat handles intelligence/discovery/social
- **Distribution**: Calibre plugin repo (111K downloads channel)

### calibre-web (13K⭐, most popular web frontend)
- **Relationship**: Parallel — both read Calibre's metadata.db
- **Differentiation**: calibre-web is a better UI for browsing. BrainyCat is intelligence + consumption (reader, player, taste engine, MCP).
- **Coexistence**: Users can run both. calibre-web for browsing, BrainyCat for reading + discovery.

### Audiobookshelf (7K⭐, audiobook-first)
- **Relationship**: Compatible — ABS mobile apps work with BrainyCat
- **Differentiation**: ABS is a mature audiobook platform. BrainyCat adds intelligence (taste engine, sleep detection, fingerprinting) on top.
- **Integration**: ABS compat shim at /compat/abs/ translates our API to ABS format.

### Kavita (7K⭐, manga/comics) & Komga (4K⭐, comics)
- **Relationship**: Complementary — different content types
- **Integration**: OPDS import lets BrainyCat search their catalogs
- **Coexistence**: BrainyCat as unified discovery layer across all servers

### Reading Apps (KOReader, Moon+ Reader, Foliate)
- **Relationship**: Client apps that connect via OPDS
- **Integration**: Our OPDS feed with pagination, OpenSearch, per-format links
- **Value-add**: They get our enriched metadata, covers, and catalog

## The Competitive Landscape

```
                    Library Management
                    ◄──────────────────────────────►

    Calibre          ██████████████████████████████████  (40+ formats, plugins, editing)
    calibre-web      ████████████████░░░░░░░░░░░░░░░░  (reads Calibre DB, web UI)
    BrainyCat        ████████░░░░░░░░░░░░░░░░░░░░░░░░  (basic CRUD, uses ebook-convert)

                    Intelligence & Discovery
                    ◄──────────────────────────────►

    BrainyCat        ██████████████████████████████████  (taste, MCP, fingerprints, social)
    Calibre          ████████░░░░░░░░░░░░░░░░░░░░░░░░  (manual enrichment, plugins)
    calibre-web      ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░  (basic search only)

                    Reading & Consumption
                    ◄──────────────────────────────►

    BrainyCat        ████████████████████████████░░░░░░  (EPUB reader, audio player, sleep mode)
    Audiobookshelf   ██████████████████████████████████  (mature audio, mobile apps)
    Kavita           ████████████████████████░░░░░░░░░░  (manga reader, EPUB reader)
    Calibre          ████████████████░░░░░░░░░░░░░░░░░░  (desktop viewer only)

                    Social & Collaboration
                    ◄──────────────────────────────►

    BrainyCat        ██████████████████████████████████  (federated profiles, clubs, lending)
    Everyone else    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  (nothing)
```

## What We Don't Do (and Why)

| Feature | Why Not |
|---|---|
| 40+ native format parsers | Use ebook-convert (Calibre). Reimplementing is years of work. |
| EPUB editing (CSS, TOC, margins) | Calibre + Sigil own this. We do merge/split + writeback. |
| Plugin marketplace | No community yet. Framework exists for when it's needed. |
| Template language for columns | Read Calibre's custom columns instead. |
| Device drivers (USB sync) | Assume WiFi/web. ABS mobile apps handle device sync. |
| Newspaper recipes | Unique to Calibre, niche use case. |
| 3D bookshelf view | Visual polish, not intelligence. Skins handle UI variety. |

## The Audiobook Market

The self-hosted audiobook space is dominated by Audiobookshelf (10K⭐). Here's where BrainyCat fits:

| Capability | ABS | Calibre | Storyteller | BrainyCat |
|---|---|---|---|---|
| Mobile apps | ✅ Native iOS/Android | ❌ | ❌ | ✅ Via ABS compat shim |
| Audiobook playback | ✅ Best-in-class | ❌ | ✅ Basic | ✅ Smart sleep mode |
| Ebook reading | ⚠️ Basic | ✅ Desktop viewer | ✅ Synced | ✅ Full reader + dictionary |
| Text↔audio sync | ❌ | ❌ | ✅ Forced alignment | ✅ Whisper STT sync maps |
| Format conversion | ❌ | ✅ 40+ formats | ❌ | ✅ 10 paths via ebook-convert |
| Metadata quality | ⚠️ Basic | ✅ 100+ sources | ❌ | ✅ 10 sources, parallel |
| AI features | ❌ | ❌ | ❌ | ✅ 28 MCP tools, taste engine, footnotes |
| Discovery | ❌ | ❌ | ❌ | ✅ 8 catalog sources, 120K+ free books |
| Social | ❌ | ❌ | ❌ | ✅ Federated profiles, clubs |

**Our strategic position**: We don't compete with ABS on mobile apps — we make their apps work with our backend (ABS compat shim). We don't compete with Calibre on format conversion — we use ebook-convert. We don't compete with Storyteller on sync — we use Whisper STT.

We compete on intelligence, discovery, and social — the layer nobody else builds.

**The convergence play**: BrainyCat is the only self-hosted platform that handles ebooks AND audiobooks with AI features, connects to ABS mobile apps, uses Calibre's conversion engine, and adds discovery + social on top. That's the winning combination the market is heading toward.

## Technical Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, PostgreSQL 16 + pgvector
- **Frontend**: Vanilla HTML/JS/CSS, EPUB.js, Chart.js
- **AI**: Intello (TTS/STT/OCR/LLM), local fallbacks
- **Conversion**: Calibre ebook-convert (9 paths)
- **Deploy**: Docker, Caddy reverse proxy
- **Mobile**: ABS compat shim (no native app needed)

## Metrics

- 95+ Python modules, ~35K lines
- 210+ API routes, 28 MCP tools
- 10 enrichment sources, 8 catalog sources (120K+ free books)
- 165+ unit tests, 22 integration tests, 33 Playwright E2E tests
- Calibre plugin ready for distribution
- 1,603 books managed on live deployment
