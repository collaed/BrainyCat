# BrainyCat Roadmap

## Current State (v1.0 — April 2026)

**58+ features implemented.** Feature-complete for r/selfhosted launch.

- 1,718 books in production library
- 32 metadata sources, continuous enrichment
- Full web reader (EPUB/PDF/MOBI) with annotations
- Audio player with chapter merge + TTS
- 12 AI features (Ask Book, Recap, Mind Maps, Auto-tag, etc.)
- 9 sync protocols (OPDS, KOReader, Kobo, WebDAV, ABS, MCP, WebSocket, Podcast RSS, OPDS-PS)
- 10 experimental features with side-by-side evaluation framework

---

## v1.1 — Polish & Stability (May 2026)

Focus: Launch readiness, first-impression quality.

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | Mobile-responsive grid improvements | Low | TODO |
| 2 | Custom error pages (404, 500) | Low | TODO |
| 3 | Rate limiting on public endpoints | Low | TODO |
| 4 | Reading challenges criteria filtering | Low | Partial (table exists) |
| 5 | Duplicate page removal UI (keep/discard) | Low | Detection done |
| 6 | AI cover generation (placeholder for books without covers) | Medium | TODO |
| 7 | Onboarding tour (first-time user walkthrough) | Medium | TODO |

---

## v1.2 — Audio & Sync (June 2026)

Focus: Audio features, deeper device sync.

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | Chapter detection for monolithic audiobooks (ML silence detection) | Medium | TODO |
| 2 | Text↔Audio sync UI (Whispersync — Intello /api/v1/align) | High | Endpoint ready |
| 3 | Voice cloning for personalized TTS (XTTS via Intello) | High | Intello wishlist |
| 4 | Kobo deep sync (full API: shelves, bookmarks, annotations) | Medium | Basics done |
| 5 | ABS mobile app: offline download, chapter images | Medium | Compat shim done |

---

## v2.0 — Multi-User & Intelligence (July–September 2026)

Focus: Team/family use, knowledge management.

### Multi-User (R2.1)
| # | Feature | Effort |
|---|---|---|
| 1 | Per-user library isolation (visibility rules) | High |
| 2 | Shared vs private books | Medium |
| 3 | Family library with parental controls | Medium |
| 4 | User roles: admin, member, guest | Low |

### Reading Intelligence (R2.7)
| # | Feature | Effort |
|---|---|---|
| 1 | Intelligence pages with 3-tier memory (session/book/lifetime) | High |
| 2 | Cross-book knowledge graph (entities, themes, connections) | High |
| 3 | "This book references..." — automatic citation detection | Medium |
| 4 | Reading patterns analysis (time of day, genre cycles) | Medium |

### Infrastructure (R2.10)
| # | Feature | Effort |
|---|---|---|
| 1 | Alembic migrations (replace raw SQL) | Medium |
| 2 | mypy strict typing | Medium |
| 3 | Test suite (pytest, 80%+ coverage) | High |
| 4 | Scheduler separation (Celery or arq) | Medium |
| 5 | Redis caching for OCR intermediate results | Low |

---

## v2.1 — Federation & Community (October 2026)

Focus: Social reading, cross-instance sharing.

| # | Feature | Effort |
|---|---|---|
| 1 | Federated profiles (ActivityPub) | High |
| 2 | Book clubs with pace-locked chapters | Medium |
| 3 | OAI-PMH protocol (metadata harvesting for libraries) | Medium |
| 4 | Prowlarr integration (auto-download wanted books) | Medium |
| 5 | Reading challenges: community-wide, leaderboards | Medium |
| 6 | Contribute enriched metadata back to Open Library (live) | Low |

---

## v3.0 — Advanced AI (2027)

Focus: Deep AI integration, research tools.

| # | Feature | Effort |
|---|---|---|
| 1 | PDF reflow (deconstruct into reflowable text) | High |
| 2 | Suffix array dedup (substring-level duplicate detection) | Medium |
| 3 | Book DNA: Spotify Wrapped with AI-generated insights | Medium |
| 4 | Research mode: citation graph, bibliography extraction | High |
| 5 | MARC Z39.50 client (query real library catalogs) | Medium |
| 6 | Semantic search across full library text (pgvector embeddings) | High |
| 7 | Auto-generated study guides from textbooks | Medium |

---

## Ideas Parking Lot

Not scheduled, evaluate when relevant:

- **Readarr deep integration** — auto-download from indexers (Readarr archived June 2025)
- **Podcast ingestion** — subscribe to podcasts, transcribe, add to library
- **Physical book scanner** — dedicated hardware (Raspberry Pi + camera) for bulk ISBN scanning
- **E-ink optimized UI** — simplified interface for Boox/Remarkable browsers
- **Handwriting recognition** — OCR stylus annotations into searchable text
- **Book marketplace** — buy/sell/trade between instances
- **Reading speed training** — progressive RSVP exercises with comprehension tests
- **Spaced repetition** — flashcards from highlights (Anki-style)

---

## Principles

1. **AI-first but graceful degradation** — everything works without Intello, AI features just disappear
2. **One entry, multiple formats** — EPUB + PDF + audiobook = one book
3. **Continuous enrichment** — never stop improving metadata quality
4. **Experimental framework** — evaluate new algorithms side-by-side before committing
5. **Protocol polyglot** — support every sync protocol readers use
6. **Self-hosted sovereignty** — no cloud dependencies, no telemetry, AGPL-3.0
