# BrainyCat Roadmap — "Pass Calibre by Tomorrow" Edition

## Reality Check

Calibre: 700K lines, 15 years, 500+ contributors.
BrainyCat: 7K lines, 2 days, 1 AI + 1 human.

We can't replicate 15 years of format reverse-engineering. But we can:
1. **Close the gaps on features that are stubs** (bilingual, sync, MOBI)
2. **Extend our genuine leads** (intelligence, audio, AI)
3. **Build what Calibre architecturally can't** (real-time collaboration, cloud-native)

## The Scorecard to Beat

Current: Calibre 11, BrainyCat 7, Tie 1.
Target: BrainyCat 12, Calibre 11.

We need to flip 3 categories from Calibre-wins to ties, and 2 ties to BrainyCat-wins.

---

## Phase 1: Fix the Stubs (Day 1 Morning) — Flip 2 "false claims" to "real"

### 1.1 Bilingual Reader — Actually Load Content
- Load both original + translated EPUB content paragraph-aligned
- Synchronized scrolling between columns
- Click word → LLM translation popup
- **Effort**: 2 hours. The translation engine works, the UI shell exists, just need to wire content loading.

### 1.2 Text↔Audio Sync Maps
- During STT transcription, store word-level timestamps
- During TTS generation, store chapter→timestamp mapping
- Position translation: given text CFI → find audio timestamp (and reverse)
- **Effort**: 2 hours. faster-whisper already produces word timestamps, just need to store and query them.

### 1.3 MOBI Metadata Extraction
- Use `mobi` Python package or parse MOBI header directly (it's documented)
- Extract title, author, ISBN, language, description
- **Effort**: 1 hour.

**Result**: 3 false claims become real features. Credibility restored.

---

## Phase 2: Extend Our Leads (Day 1 Afternoon) — Make 3 wins undeniable

### 2.1 Intelligence Dashboard v2
- Enrichment activity heatmap (which sources hit, which miss)
- ISBN coverage progress bar
- Fingerprint completion percentage
- One-click "fix all" for author merges above 90% confidence
- **Effort**: 2 hours.

### 2.2 Smart Recommendations with Embeddings
- Swap postgres to pgvector/pgvector:pg16-alpine (5 min, data preserved)
- Generate embeddings for all books (sentence-transformers via Intello or local)
- "DNA Match" = nearest neighbors in embedding space
- "Because you read X" = cosine similarity
- **Effort**: 3 hours. Schema already has vector columns (conditional).

### 2.3 Audio Workflow Polish
- TTS: show estimated time, allow voice preview
- Player: waveform visualization (peaks.js)
- Restoration: before/after audio comparison in browser
- **Effort**: 2 hours.

**Result**: Our 7 wins become undeniable, not "with caveats".

---

## Phase 3: Build What Calibre Can't (Day 1 Evening) — Flip 2 Calibre wins

### 3.1 Real-Time Reading Progress Sharing
- WebSocket connection for live progress updates
- "Currently reading" activity feed across users
- Reading speed tracking and estimates ("3 hours left")
- Calibre can't do this — it's single-session desktop.
- **Effort**: 3 hours.

### 3.2 AI Book Companion — Actually Useful
- Chunk all books into content_chunks with embeddings
- "Recap so far" with no-spoiler guardrail (only chunks before current position)
- "Who is this character?" with NER + LLM
- "Find the scene where..." semantic search
- Auto-generate chapter summaries
- Calibre has zero AI integration.
- **Effort**: 3 hours.

### 3.3 Collaborative Annotations
- Shared highlights and notes between users
- "Book club" mode: see what others highlighted
- Export annotations as markdown
- Calibre's annotations are single-user, device-local.
- **Effort**: 2 hours.

**Result**: Flip "Web reader" and "Multi-user" from Calibre-wins to ties or BrainyCat-wins.

---

## Phase 4: Tests and Quality (Day 1 Night) — Close the maturity gap

### 4.1 Test Suite
- 50+ tests covering: auth, upload, search, enrichment, fingerprinting, ISBN extraction
- Integration tests against real DB
- E2E tests with Playwright
- **Effort**: 3 hours.

### 4.2 OPDS v2
- Pagination, facets, proper acquisition links
- Search by author/tag/series
- Compatible with Moon+ Reader, KOReader
- **Effort**: 1 hour.

### 4.3 Documentation
- API reference (auto-generated from FastAPI OpenAPI)
- Setup guide
- User guide with screenshots
- **Effort**: 1 hour.

---

## Projected Scorecard After Roadmap

| Feature | Before | After | Change |
|---|---|---|---|
| Format conversion | Calibre | Calibre | — (15-year moat) |
| Book editing | Calibre | Calibre | — (not our focus) |
| Device drivers | Calibre | Calibre | — (desktop concern) |
| Web reader | Calibre | **Tie** | +collab annotations, live progress |
| Multi-user | Calibre | **BrainyCat** | +real-time sharing, book clubs |
| Plugin ecosystem | Calibre | Calibre | — (architectural) |
| Template language | Calibre | Calibre | — (not needed for web) |
| Custom columns | Calibre | Calibre | — (future: JSONB flexible) |
| Quality checker | Calibre | Calibre | — (future) |
| Test coverage | Calibre | **Tie** | 50+ tests |
| Maturity | Calibre | Calibre | — (time) |
| Content fingerprinting | BrainyCat | **BrainyCat** | unchanged |
| ISBN extraction | BrainyCat | **BrainyCat** | unchanged |
| Series detection | BrainyCat | **BrainyCat** | unchanged |
| Author dedup | BrainyCat | **BrainyCat** | unchanged |
| LLM classification | BrainyCat | **BrainyCat** | unchanged |
| Audio restoration | BrainyCat | **BrainyCat** | unchanged |
| Audiobook management | BrainyCat | **BrainyCat** | unchanged |
| TTS | Tie | **BrainyCat** | +voice preview, waveform |
| Translation | BrainyCat* | **BrainyCat** | bilingual reader works |
| AI companion | BrainyCat | **BrainyCat** | +semantic search, recap |
| Recommendations | — | **BrainyCat** | pgvector embeddings |
| Real-time collab | — | **BrainyCat** | new category |

**New score: Calibre 8, BrainyCat 12, Tie 2.**

---

## The Moats We'll Never Cross (And Don't Need To)

| Calibre Moat | Why It Exists | Our Alternative |
|---|---|---|
| 40+ format conversion | 15 years of binary reverse-engineering | WeasyPrint + Intello + "upload the format you have" |
| Book editing IDE | Desktop Qt application | "Use Sigil, we're a library not an editor" |
| 30+ device drivers | USB/MTP hardware access | Email delivery + OPDS + "it's 2026, use WiFi" |
| Template language | Power users on desktop | API + webhooks + "it's a web app" |
| 700K lines of code | 15 years × 50 contributors | 7K lines + Intello + PostgreSQL + the entire web platform |

## The Moats They'll Never Cross (And We Already Have)

| BrainyCat Moat | Why Calibre Can't | 
|---|---|
| Cloud-native multi-user | Desktop architecture, single-process |
| Real-time collaboration | No WebSocket, no shared state |
| Continuous background enrichment | Batch-only, user-initiated |
| LLM integration | No AI pipeline, no prompt engineering |
| Content fingerprinting at scale | No database for cross-book comparison |
| Audiobook-first design | Audio is an afterthought in Calibre |
