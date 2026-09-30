# Architecture

## System Diagram

```
┌──────────────── sake (home server) ────────────────┐
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │ brainycat container (port 8000)              │  │
│  │                                              │  │
│  │  FastAPI (uvicorn, 1 worker)                 │  │
│  │  ├── 18 route modules                        │  │
│  │  ├── 15 background asyncio loops             │  │
│  │  └── volume mounts:                          │  │
│  │       /data → brainycat-data volume          │  │
│  │       /app/brainycat → ./brainycat (live)    │  │
│  │       /app/static → ./static (live)          │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │ asyncpg                           │
│  ┌──────────────▼───────────────────────────────┐  │
│  │ brainycat-db (PostgreSQL 16 + pgvector)      │  │
│  │ port 5432 internal only                      │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │ intello container (port 8000 internal)       │  │
│  │ AI server — BUT unreachable from brainycat   │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘

┌──────────────── ecb.pm (VPS) ──────────────────────┐
│  Caddy → tools.ecb.pm/brainycat/* → brainycat:8000 │
│  Problem: no brainycat container here.             │
│  This path is BROKEN.                              │
└────────────────────────────────────────────────────┘
```

## Process Model

Single-process, single-worker. No multiprocessing, no Celery, no Redis.

```
uvicorn (1 worker)
 ├── FastAPI HTTP handlers (request/response)
 ├── 15 asyncio.Task background loops (never terminate)
 └── asyncpg connection pool (shared by all)
```

The main consequence: a misbehaving background loop that holds a DB connection or does blocking I/O will starve HTTP handlers. The `statement_timeout` in PostgreSQL is the safety valve — it kills queries stuck longer than 30s.

## Startup Sequence

1. Alembic runs migrations (5 retries, 3s delay between)
2. Uvicorn starts the FastAPI app
3. `lifespan()` fires:
   - Creates asyncpg pool
   - Seeds admin user (if none exists)
   - Starts all 15 scheduler loops (staggered 15-45s)
   - Triggers offline bootstrap (OL/BnF dump download if enabled)
4. `startup` event:
   - Initializes shared HTTPX client
   - Seeds rate-limit state from DB (remembered backoffs survive restarts)

## Request Lifecycle

```
HTTP request
  → NoCacheStatic middleware (Cache-Control: no-store for /static/)
  → FastAPI routing (18 routers)
  → Route handler
    → auth check (JWT cookie or API key header)
    → asyncpg query (from pool)
    → response
```

No ORM. All SQL is raw strings passed to asyncpg. Helpers:
- `fetch_one(sql, *args)` → dict | None
- `fetch_all(sql, *args)` → list[dict]
- `execute(sql, *args)` → status string

## Module Dependency Graph

```
web.py
 ├── routes/ (18 files)
 │    ├── books.py → books.py, covers.py, isbn.py, convert.py
 │    ├── admin.py → intelligence.py, stats.py, scheduler.py
 │    ├── enrichment.py → metadata.py, isbn.py, fingerprints.py
 │    ├── reader.py → reading_progress, annotations, opds
 │    └── ...
 ├── scheduler.py
 │    ├── metadata.py → sources/* (20 adapters), rate_limit.py
 │    ├── fast_local.py → ol_local.py (SQLite)
 │    ├── confidence.py → db queries
 │    ├── text_profiler.py → incipit.py, embeddings.py
 │    └── watcher.py → ingest.py → extract.py
 └── db.py (asyncpg pool — used by everything)
```

## Networks (Docker)

On sake:
- `web` network: brainycat + intello (supposed to be reachable by name)
- `db` network: brainycat + brainycat-db

The `.env` sets `BRAINYCAT_INTELLO_URL=http://intello:8000`. Both containers are on the `web` network, but the enrichment loop still times out — likely because intello itself can't reach external APIs it depends on, or its internal route `/api/v1/lookup` is broken.

## Code Organization

| Directory | Purpose | Size |
|-----------|---------|------|
| `brainycat/` | All Python backend code | 100+ files |
| `brainycat/routes/` | FastAPI routers (18) | ~8K lines total |
| `brainycat/sources/` | One file per external API source | 20 files |
| `brainycat/experimental/` | Feature flags, not in main paths | 13 files |
| `brainycat/importers/` | Calibre/KOReader import adapters | 3 files |
| `brainycat/translators/` | Language pair translation modules | 2 files |
| `static/` | Vanilla HTML/JS/CSS (no build step) | 30+ files |
| `scripts/` | One-off data processing scripts | 5 files |
| `migrations/versions/` | Alembic DDL migrations | 5 files |
| `tests/` | pytest (unit, integration, e2e) | 40+ files |
| `cli/` | `brainycat` CLI tool | 1 file |
| `ebook-convert-rs/` | Rust EPUB converter (alternative to Calibre) | Cargo project |
| `calibre-plugin/` | Calibre integration plugin | 3 files |

## Technology Choices

| Layer | Choice | Why |
|-------|--------|-----|
| Web framework | FastAPI | Async native, good for background tasks |
| Database | PostgreSQL 16 | pgvector, pg_trgm, unaccent, mature |
| DB driver | asyncpg | Fastest Python PostgreSQL driver |
| HTTP client | httpx (async) | For source API calls |
| Local enrichment | SQLite (via sqlite3) | 30M rows, instant lookups |
| EPUB parsing | ebooklib | Read/write EPUB metadata |
| PDF parsing | PyMuPDF (fitz) | Page rendering, text extraction |
| Barcode detection | pyzbar | ISBN from scanned pages |
| Format conversion | calibre (ebook-convert) | Reliable, all formats |
| TTS | Piper (local) + Groq via Intello | Offline capability |
| Embeddings | sentence-transformers | Semantic search, dedup |
| Frontend | Vanilla HTML/JS | No build step, no node |
| Deployment | Docker + docker-compose | Simple, reproducible |
