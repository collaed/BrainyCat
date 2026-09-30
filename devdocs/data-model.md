# Data Model

## PostgreSQL Schema

42 tables total. The core ones:

```
┌─────────────────────────────────────────────────────────────────┐
│                         books (63,504 rows)                      │
├─────────────────────────────────────────────────────────────────┤
│ id            UUID PK                                           │
│ title         TEXT                                               │
│ sort_title    TEXT (computed: "Art of War, The")                 │
│ isbn          TEXT (nullable — 43% have it)                     │
│ description   TEXT (nullable — 2.2% have it)                    │
│ cover_path    TEXT (nullable — 74% have it)                     │
│ quality_score INTEGER (0-100, avg 11.9)                         │
│ pubdate       DATE (nullable — 36% have it)                     │
│ series_index  REAL (nullable, e.g., 1.0, 2.0)                  │
│ extra_metadata JSONB (the junk drawer — see below)              │
│ search_vector TSVECTOR (GIN indexed, FTS)                       │
│ embedding     VECTOR(384) (pgvector, semantic search)           │
│ is_workbook   BOOLEAN                                           │
│ created_at    TIMESTAMPTZ                                       │
│ updated_at    TIMESTAMPTZ                                       │
└─────────────────────────────────────────────────────────────────┘
          │ 1:N              │ M:N              │ M:N
          ▼                  ▼                  ▼
┌─────────────────┐ ┌───────────────┐ ┌───────────────────┐
│ book_files      │ │ books_authors │ │ books_languages   │
│ ─────────────── │ │ ───────────── │ │ ───────────────── │
│ id, book_id     │ │ book_id       │ │ book_id           │
│ file_path       │ │ author_id     │ │ language_id       │
│ format          │ └───────┬───────┘ └────────┬──────────┘
│ file_size       │         │                  │
│ file_hash       │         ▼                  ▼
│ original_name   │ ┌───────────────┐ ┌───────────────────┐
└─────────────────┘ │ authors       │ │ languages         │
                    │ (7,305 rows)  │ │                   │
                    └───────────────┘ └───────────────────┘
```

## The `extra_metadata` JSONB Column

This is where things get messy. It's a schemaless escape hatch that holds everything that doesn't have a dedicated column:

| Key | Type | Books with it | Purpose |
|-----|------|---------------|---------|
| `local_enriched` | boolean (`true`) | 27,351 | Flag: OL SQLite lookup done |
| `local_title_tried` | boolean OR object | 16,121 (9K bool + 7K obj) | Title matching result |
| `content_signals` | object | 36,961 | Detected language, reading level |
| `validation` | object | 24,460 | Metadata vs content cross-check |
| `confidence_score` | number | varies | 0-100 identification confidence |
| `confidence_conflicts` | array | varies | Conflicting signals |
| `isbn_source` | string | varies | How ISBN was obtained |
| `ol_work_id` | string | varies | Open Library work identifier |
| `cover_phash` | string | varies | Perceptual hash of cover |
| `incipit` | string | varies | First 200 characters of text |
| `bisac_codes` | array | varies | Genre classification codes |
| `edition_info` | object | varies | Publisher, pages, edition |
| `title_fixed` | boolean | varies | Title was cleaned |
| `language_mismatch` | object | 175 | Detected ≠ enrichment language |
| `isbn_ocr_tried` | boolean | varies | OCR copyright extraction attempted |

**Type safety problem:** `local_title_tried` is sometimes `true` (boolean, meaning "attempted but no match") and sometimes a dict (meaning "matched, here are details"). This causes the confidence bug.

## Relationship Tables

| Table | Purpose | Row count context |
|-------|---------|-------------------|
| `books_authors` | M:N books ↔ authors | 41,442 books have authors |
| `books_languages` | M:N books ↔ languages | 35,150 books have language |
| `books_publishers` | M:N books ↔ publishers | 23,455 books have publisher |
| `books_tags` | M:N books ↔ tags | 10,327 books have tags |
| `books_series` | M:N books ↔ series | — |

## Supporting Tables

| Table | Purpose |
|-------|---------|
| `enrichment_log` | Every enrichment attempt: method, success, book_id, timestamp (79,361 rows) |
| `book_files` | Physical files per book (multiple formats possible) |
| `book_fingerprints` | Content fingerprints for dedup |
| `duplicate_matches` | Pairs of suspected duplicates |
| `annotations` | Reader highlights and notes |
| `reading_progress` | Per-user reading position |
| `bookmarks` | Saved positions |
| `content_index` | FTS on book content |
| `content_chunks` | Chunked text for RAG/search |
| `incoming_items` | Files in the watch folder |
| `filename_history` | Audit trail of file renames |
| `metadata_history` | Audit trail of metadata changes |
| `kv_store` | Key-value pairs (rate limits, settings) |
| `users` | User accounts |
| `user_preferences` | Per-user settings |
| `collections` | User-created shelves |
| `collection_books` | M:N collection ↔ books |
| `series` | Series metadata |
| `tags` | Tag definitions (6,964 unique) |
| `authors` | Author definitions (7,305 unique) |
| `publishers` | Publisher definitions |
| `languages` | Language definitions |
| `taste_profiles` | User taste DNA for recommendations |
| `jobs` | Async background jobs |
| `job_logs` | Job execution history |
| `podcast_feeds` | RSS podcast subscriptions |
| `audio_chapters` | Chapter markers for audiobooks |
| `audio_diagnostics` | Audio quality analysis |
| `sync_maps` | Text ↔ audio alignment maps |
| `consumption_rules` | Auto-tagging rules |
| `bug_candidates` | Flagged metadata issues |
| `book_links` | Inter-book relationships |
| `book_notes` | User notes on books |
| `book_reviews_cache` | Cached external reviews |
| `book_translations` | Translation relationships |

## Extensions

| Extension | Purpose |
|-----------|---------|
| `pgvector` | `VECTOR(384)` column for semantic search |
| `pg_trgm` | Fuzzy text matching (`similarity()`, `%` operator) |
| `unaccent` | Diacritic-insensitive search |

## Indexes (what exists)

```sql
-- GIN on search_vector (FTS)
-- GIN on extra_metadata (JSONB containment)
-- IVFFlat on embedding (pgvector ANN search)
-- btree on isbn
-- btree on created_at
-- Various FK indexes on relationship tables
```

## Indexes (what's MISSING — causing statement_timeout)

```sql
-- These would fix the scheduler loops:
CREATE INDEX idx_books_quality ON books (quality_score);
CREATE INDEX idx_books_no_local ON books (id) WHERE (extra_metadata->>'local_enriched') IS NULL;
CREATE INDEX idx_books_isbn_null ON books (id) WHERE isbn IS NULL;
CREATE INDEX idx_books_cover_null ON books (id) WHERE cover_path IS NULL;
```

## SQLite Databases (local enrichment)

| File | Size | Source | Records |
|------|------|--------|---------|
| `/data/isbn_lookup.db` | 2-4GB | Open Library editions dump | ~30M |
| `/data/bnf_lookup.db` | ~500MB | BnF SPARQL dump | ~4.7M |

These are queried by `fast_local.py` and `ol_local.py`. They're regeneratable from public data — `offline_bootstrap.py` handles download + indexing.
