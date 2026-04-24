# BrainyCat v2 — Requirements

*v1 shipped in 3 days (2026-04-22 → 2026-04-24). v2 is the "make it real" release.*

## 1. Multi-User Library System

**Problem:** Every r/selfhosted thread asks for per-user libraries. Currently all users see all books.

### Requirements
- R2.1.1: Each book has an `owner_id` (the user who uploaded it)
- R2.1.2: Books can be `private` (owner only), `shared` (specific users/groups), or `public` (all users)
- R2.1.3: Admin can create **groups** (e.g., "Family", "Book Club", "Research Team")
- R2.1.4: A **community library** exists where users can publish books for all to see
- R2.1.5: Users see only: their own books + shared with them + community library
- R2.1.6: Reading progress, annotations, clippings, pen strokes are always per-user (even on shared books)
- R2.1.7: Enrichment metadata is shared (one enrichment benefits all users who have the same book)
- R2.1.8: **Dedup across users**: if 50 users upload the same ISBN, store the file once. Each user gets a "virtual copy" with their own progress/annotations. Metadata is canonical (from enrichment), user can overlay with personal notes in a sidecar.
- R2.1.9: Admin dashboard shows per-user storage usage
- R2.1.10: OIDC/OAuth2 login (Google, Keycloak, Authentik) alongside local auth

### Schema Changes
```sql
ALTER TABLE books ADD COLUMN owner_id uuid REFERENCES users(id);
ALTER TABLE books ADD COLUMN visibility text DEFAULT 'private'; -- private/shared/public
CREATE TABLE book_shares (book_id uuid, user_id uuid, group_id uuid);
CREATE TABLE groups (id uuid, name text, created_by uuid);
CREATE TABLE group_members (group_id uuid, user_id uuid, role text);
-- Dedup: canonical_book_id links user copies to a single file
ALTER TABLE books ADD COLUMN canonical_id uuid REFERENCES books(id);
```

---

## 2. Book Status & Reading Lifecycle

**Problem:** No way to say "I want to read this" or "I finished this." Progress % is not enough.

### Requirements
- R2.2.1: Book status enum: `want_to_read`, `reading`, `finished`, `abandoned`, `library_only`
- R2.2.2: Status changes are timestamped (`started_at`, `finished_at`, `abandoned_at`)
- R2.2.3: "Want to Read" list is browsable as a shelf
- R2.2.4: "Currently Reading" shows on dashboard with progress bar + ETA
- R2.2.5: "Finished" count feeds into reading goals
- R2.2.6: Status can be set from library grid (quick action), book detail, and reader
- R2.2.7: Filter library by status

### Schema Changes
```sql
ALTER TABLE reading_progress ADD COLUMN status text DEFAULT 'library_only';
ALTER TABLE reading_progress ADD COLUMN started_at timestamptz;
ALTER TABLE reading_progress ADD COLUMN finished_at timestamptz;
```

---

## 3. Daily Reading Logs & Streaks

**Problem:** We track position but not "how much did I read today." Needed for streaks, speed trends, wrap-ups.

### Requirements
- R2.3.1: Log entry: `{user_id, book_id, date, pages_read, minutes_read, position_start, position_end}`
- R2.3.2: Auto-generated from reading progress changes (reader reports position on close/page-turn)
- R2.3.3: Manual entry option ("I read 30 pages of X today on paper")
- R2.3.4: Streak calculation: consecutive days with at least 1 page read
- R2.3.5: Streak displayed on dashboard with current + longest
- R2.3.6: Weekly/monthly reading time summaries
- R2.3.7: Reading speed: pages/hour, words/minute, by genre, over time

### Schema
```sql
CREATE TABLE reading_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    book_id uuid NOT NULL REFERENCES books(id),
    date date NOT NULL,
    pages_read int,
    minutes_read int,
    UNIQUE (user_id, book_id, date)
);
```

---

## 4. Book DNA & Wrap-Up Cards

**Problem:** "Spotify Wrapped for books" — the feature BookTok would love. We have all the data.

### Requirements
- R2.4.1: **Monthly wrap-up**: books finished, total pages, total hours, top genre, top author, longest streak
- R2.4.2: **Yearly wrap-up**: same + reading pace trend, genre distribution pie chart, "you read more than X% of users"
- R2.4.3: Generated as SVG → PNG (shareable image, no external service)
- R2.4.4: **Book DNA radar chart**: fiction/non-fiction ratio, genre spread, avg book length, reading pace, language diversity
- R2.4.5: Shareable via URL (public page, no auth required) or downloadable image
- R2.4.6: Embeddable widget (`<iframe>` or `<img>` tag) for blogs/Notion

### Endpoints
```
GET /api/v1/wrap-up/monthly?month=2026-04 → SVG/PNG
GET /api/v1/wrap-up/yearly?year=2026 → SVG/PNG
GET /api/v1/book-dna/{user_id} → SVG radar chart
GET /public/wrap-up/{share_token} → public shareable page
```

---

## 5. Audio/Text Progress Sync (Whispersync)

**Problem:** 4-day-old thread: "Are there services that sync progress between listening and reading?" Answer: "No perfect all-in-one yet."

### Requirements
- R2.5.1: When a book has both EPUB and audio files, link them as a "paired book"
- R2.5.2: Use STT (Intello/Whisper) to transcribe audio → text alignment map
- R2.5.3: Alignment map: `{audio_timestamp → epub_cfi}` at paragraph level
- R2.5.4: When user switches from audio to text (or vice versa), position translates automatically
- R2.5.5: "Continue reading" and "Continue listening" buttons on book detail
- R2.5.6: Graceful degradation: if no alignment map, show both positions independently

### Dependencies
- Intello STT endpoint
- Paragraph-level text extraction from EPUB
- Alignment algorithm (forced alignment or fuzzy text matching)

---

## 6. File Watcher & Auto-Import

**Problem:** "I want to drop files via Samba/NFS and have them appear in the library."

### Requirements
- R2.6.1: Watch a configurable directory (`BRAINYCAT_INCOMING_DIR`) for new files
- R2.6.2: Debounce: wait 5 seconds after last file change before processing
- R2.6.3: Supported: all 22 upload formats
- R2.6.4: On detection: move to library → extract metadata → create book entry → enrich
- R2.6.5: Ignore patterns: `.part`, `.tmp`, `.crdownload`, dotfiles
- R2.6.6: Recursive watching (subdirectories)
- R2.6.7: Log all imports with source path and result
- R2.6.8: Optional: assign imported books to a specific user/group based on subdirectory name

---

## 7. Intelligence Pages (Wiki-First RAG)

**Problem:** Book detail page is just metadata. Should be a rich intelligence page.

### Requirements
- R2.7.1: Each book gets a pre-generated **intelligence page** with sections:
  - Summary (3 levels: quick / detailed / goldmine)
  - Key themes and concepts
  - Character list with descriptions (fiction)
  - Chapter summaries
  - Notable quotes (extracted from text)
  - Related books in library
  - External links (Wikipedia, Goodreads, author site)
- R2.7.2: Generated by LLM on first enrichment, cached as HTML
- R2.7.3: **Deterministic fallback**: if LLM fails, show what we have (metadata, description, similar books)
- R2.7.4: **Splice pattern**: after LLM generation, detect missing sections via regex, append deterministic replacements
- R2.7.5: Regenerate on demand (button in UI)
- R2.7.6: Sections build incrementally (summary first, themes later, characters when user reads past 50%)

### 3-Tier Memory (Beever Atlas pattern)
- **Tier 2**: Atomic facts — passages, quotes, highlights extracted from book text
- **Tier 1**: Topic clusters — chapter themes, concept groups (consolidated from Tier 2)
- **Tier 0**: Book summary — synthesized from Tier 1 clusters

---

## 8. Prowlarr Integration

**Problem:** *arr users want BrainyCat in their existing stack.

### Requirements
- R2.8.1: BrainyCat can act as a Prowlarr-compatible application (like Sonarr/Radarr)
- R2.8.2: Search Prowlarr indexers from BrainyCat's Discover tab
- R2.8.3: Send downloads to qBittorrent/SABnzbd via Prowlarr
- R2.8.4: Monitor completed downloads → auto-import to library
- R2.8.5: Optional — not required for core functionality

---

## 9. WebSocket Real-Time Updates

**Problem:** Multiple users browsing simultaneously don't see changes until refresh.

### Requirements
- R2.9.1: WebSocket endpoint at `/ws/library`
- R2.9.2: Events: `book_added`, `book_enriched`, `book_deleted`, `progress_updated`, `ocr_complete`
- R2.9.3: Authenticated (session token in connection handshake)
- R2.9.4: UI updates in real-time (new book appears in grid, quality score updates, cover loads)
- R2.9.5: Lightweight — no full book data in events, just IDs + changed fields

---

## 10. Architecture Hardening

### Requirements
- R2.10.1: **Alembic migrations** for all 33+ tables (currently 2 migrations)
- R2.10.2: **mypy strict mode** in CI
- R2.10.3: **Test coverage > 60%** with DB fixtures (testcontainers-python)
- R2.10.4: **books.py split** — 1,483 lines → books_crud.py, books_bulk.py, books_series.py, books_collections.py
- R2.10.5: **Separate scheduler process** — enables multi-worker uvicorn without duplicate background tasks
- R2.10.6: **IVFFlat reindex** — auto-tune lists parameter based on book count
- R2.10.7: **Batch tag insertion** — single INSERT for N tags instead of N queries
- R2.10.8: **Circuit breaker for Intello** — after 5 consecutive failures, stop calling for 5 minutes
- R2.10.9: **Health endpoint** returns component status (DB, Intello, disk, scheduler)
- R2.10.10: **Structured error responses** — consistent `{error, code, detail}` across all endpoints

---

## Non-Functional Requirements

| Requirement | Target |
|---|---|
| Cold start (docker compose up → first page) | < 30 seconds |
| Library page load (1,000 books) | < 500ms |
| Cover grid (50 covers) | < 2 seconds (with caching) |
| Enrichment throughput | 5 books/minute sustained |
| OCR throughput | 1 book/5 minutes (via Intello) |
| Memory (idle, 5K books) | < 512MB |
| Disk per 1K books (files + metadata) | ~5GB average |
| Concurrent users | 50 (single worker + semaphore) |
| Backup size (10K books metadata) | < 50MB gzipped |
| Uptime (scheduler crash recovery) | < 60 seconds to restart loop |

---

## Milestones

| Milestone | Features | Target |
|---|---|---|
| **v2.0-alpha** | Multi-user isolation, book status, daily logs | +2 weeks |
| **v2.0-beta** | Wrap-up cards, file watcher, WebSocket | +4 weeks |
| **v2.0-rc** | Intelligence pages, Prowlarr, architecture hardening | +8 weeks |
| **v2.0** | Audio/text sync, full test coverage, docs | +12 weeks |
