# BrainyCat — Calibre Companion Path

## Vision

BrainyCat as the AI reading companion for Calibre libraries.
Calibre owns files, metadata, organization, conversion.
BrainyCat owns intelligence, discovery, consumption, social.

## Phase A: Read-Only Overlay

- Point BrainyCat at a Calibre metadata.db (read-only)
- Query catalog data directly (titles, authors, ISBNs, file paths, covers)
- Write all intelligence to PostgreSQL, keyed by Calibre book ID
- Never touch metadata.db directly
- **Effort**: 1-2 days

## Phase B: Shadow Metadata

- BrainyCat enriches, corrects, classifies — stores in PostgreSQL as overlay
- Display: merge Calibre data + BrainyCat enrichments
- Pending changes queue: "12 books have better ISBNs ready to push"
- **Effort**: 1 day

## Phase C: Calibre Sync Plugin (Python, InterfaceActionBase)

- Runs inside Calibre's process — safe DB access via `db.new_api`
- Toolbar button: "Sync with BrainyCat"
- Calls BrainyCat API for pending changes
- Applies via `db.new_api.set_field()` — handles file renames safely
- Pushes covers via `db.new_api.set_cover()`
- Reports back what was synced
- Scheduled sync option (every N hours)
- **Effort**: 2-3 days
- **Distribution**: Calibre plugin repository (111K downloads channel)

## Phase D: Calibre Content Server Proxy

- BrainyCat sits in front of calibre-server
- Passes catalog/download requests through to Calibre unchanged
- Adds intelligence overlay: taste recommendations on home page,
  "you fell asleep here" on player, fingerprint-based "you already own this"
- Users get BrainyCat UX with Calibre engine, zero migration
- **Effort**: 3-5 days

## Phase E: Deep Integration

- Plugin features:
  - "Open in BrainyCat" button in Calibre UI → launches browser
  - Show BrainyCat quality score in Calibre custom column
  - Show taste match % in Calibre custom column
  - Push reading progress from BrainyCat → Calibre's last_read_positions
  - Trigger BrainyCat enrichment from Calibre's context menu
- BrainyCat features:
  - Read Calibre's virtual libraries and saved searches
  - Read Calibre's custom columns natively
  - Respect Calibre's tag browser hierarchy
- **Effort**: 1-2 weeks

## Architecture

```
┌─────────────────────┐     ┌──────────────────────────┐
│     Calibre          │     │      BrainyCat            │
│                      │     │                          │
│  metadata.db ◄──READ──────── catalog queries          │
│  book files  ◄──READ──────── file serving             │
│                      │     │                          │
│  db.new_api ◄──PLUGIN──────── pending changes         │
│  (safe writes)       │     │                          │
│                      │     │  PostgreSQL:             │
│                      │     │  - fingerprints          │
│                      │     │  - embeddings            │
│                      │     │  - taste profiles        │
│                      │     │  - sleep events          │
│                      │     │  - enrichment overlay    │
│                      │     │  - reading progress      │
│                      │     │  - social/clubs          │
│                      │     │  - MCP tools             │
└─────────────────────┘     └──────────────────────────┘
```

## Why This Wins

- No data duplication — Calibre is the source of truth for catalog
- No migration — users keep their existing Calibre library
- No conflict — BrainyCat never writes to metadata.db
- Safe sync — plugin uses Calibre's own API for write-back
- Distribution — Calibre plugin repo gives us access to 100K+ users
- Focus — we build intelligence, not another library manager
