# BrainyCat Developer Wiki

> The honest-to-god state of this project. No marketing. Written so future-you can pick it up after 3 months away.

**Verified:** 2026-06-04 16:49 CEST · **63,504 books** · **avg quality 11.9/100** · enrichment mostly stalled

---

## The 30-Second Picture

BrainyCat is a self-hosted ebook library that:
1. Stores books (22 formats, upload or watch folder)
2. Tries to automatically enrich them with metadata from 32 sources
3. Lets you read them in the browser (EPUB/PDF reader)

It's a **single FastAPI process** + **PostgreSQL 16** running on sake. No Redis, no Celery, no workers. Background enrichment runs as 15 asyncio tasks inside the main process. The only optional external service is Intello (LLM/OCR/TTS), currently unreachable from sake.

### What Actually Works Right Now

| Feature | Real status |
|---------|-------------|
| Upload & store | ✅ Solid |
| EPUB/PDF reader | ✅ Works |
| Local SQLite enrichment (ISBN) | ✅ Running, ~700 books/day |
| Covers | ⚠️ 74% coverage, no new ones being fetched |
| API enrichment (OL, Google, etc.) | ❌ All timing out |
| LoC enrichment | ❌ 11,969 attempts, 0 hits |
| Confidence scoring | ❌ Bug every 60s (`'bool' object has no attribute 'get'`) |
| External access (tools.ecb.pm) | ❌ Broken — no container on ecb.pm |
| Direct access (sake:8000) | ✅ Works |

### What The README Claims vs Reality

| Metric | README | Actual |
|--------|--------|--------|
| Avg quality | 67.9 | **11.9** |
| Language | 94% | **55%** (35,150) |
| Descriptions | 61% | **2.2%** (1,387) |
| ISBN | 80% | **43%** (27,354) |
| Covers | 99.9% | **74%** (46,892) |
| Authors | — | **65%** (41,442) |
| Pubdate | 46% | **36%** (22,631) |

---

## Navigation

| Document | What's in it |
|----------|--------------|
| [Architecture](architecture.md) | Module map, request lifecycle, component diagram |
| [Data Model](data-model.md) | PostgreSQL schema (42 tables), JSONB patterns, relationships |
| [Enrichment Pipeline](enrichment-pipeline.md) | 32 sources, local-first strategy, merge logic, what's broken |
| [Scheduler](scheduler.md) | 15 loops, supervision model, what's working vs stalled |
| [Confidence Scoring](confidence.md) | 7-signal model, the bool bug, quality distribution |
| [ISBN Intelligence](isbn-intelligence.md) | 6 extraction methods, 285 registration groups, Unicode handling |
| [Reader](reader.md) | EPUB/PDF rendering, progress sync, annotations, stylus |
| [Catalog & Discovery](catalog-discovery.md) | 15 free sources, OPDS, taste engine |
| [Deployment](deployment.md) | Docker, env vars, access paths, the ecb.pm problem |
| [MCP Server](mcp-server.md) | 22 tools, stdio transport |
| [Bugs & Debt](bugs.md) | Known issues ranked by impact, fix suggestions |
| [Operations Runbook](runbook.md) | How to check health, restart, debug, fix enrichment |

---

## Key Design Decisions (and their consequences)

| Decision | Rationale | Consequence |
|----------|-----------|-------------|
| No task queue (asyncio only) | Zero deps, simpler deployment | Can't scale horizontally; one stuck loop blocks DB connections |
| PostgreSQL for everything | pgvector, pg_trgm, FTS, no second store | statement_timeout kills complex queries; 42 tables is a lot |
| Source adapters never raise | Graceful degradation | Silent failures hide broken sources for weeks |
| JSONB `extra_metadata` as escape hatch | No migrations for new fields | Type safety disaster (booleans where dicts expected) |
| Local-first enrichment (SQLite) | 1000x faster than APIs | 2-4GB disk; stale data (OL dump is months old) |
| Intello as optional dep | AI features degrade gracefully | When Intello is down, enrichment loop wastes 6 slots every 10s trying |

---

## Critical Path To Fixing Things

1. **Stop the bleeding** — The enrichment loop tries external APIs every 10s and times out every time. Either fix connectivity to Intello/APIs from sake, or make the loop skip when unreachable.
2. **Fix confidence bug** — 9,048 books have `extra_metadata.local_title_tried = true` (boolean). The confidence scorer hits `.get()` on this. Quick fix: add `isinstance` guard.
3. **Fix or disable LoC** — 11,969 attempts, 0 successes. It's burning rate-limit budget for nothing.
4. **Fix tools.ecb.pm access** — Caddy on ecb.pm proxies to `brainycat:8000` Docker DNS, but the container is on sake. Fix: change upstream to `sake_ip:8000`.
5. **Correct the README stats** — They're 3-10x inflated. Replace with real numbers.

---

## Quick Reference

```bash
# SSH to sake, check container health
ssh sake "docker ps --filter name=brainycat"

# Tail logs (enrichment_timeout = normal right now, unfortunately)
ssh sake "docker logs brainycat --tail 50 2>&1"

# DB shell
ssh sake "docker exec -it brainycat-db psql -U brainycat brainycat"

# Quick stats
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT COUNT(*) as total,
         COUNT(isbn) as with_isbn,
         COUNT(cover_path) as with_cover,
         COUNT(description) as with_desc,
         ROUND(AVG(quality_score),1) as avg_quality
  FROM books;\""

# Enrichment in last 24h
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT method, success, COUNT(*) FROM enrichment_log
  WHERE created_at > now() - interval '24 hours'
  GROUP BY method, success ORDER BY count DESC;\""

# Restart (code is volume-mounted so changes take effect)
ssh sake "docker restart brainycat"
```

---

## Module Map (by importance)

```
brainycat/
├── web.py              (139 lines — FastAPI app, lifespan, middleware)
├── scheduler.py        (25K — 15 loops, _supervised() wrapper)
├── metadata.py         (20K — source orchestration, merge, relevance guard)
├── isbn.py             (33K — 6 extraction methods, registration groups)
├── fast_local.py       (9K — local SQLite enrichment engine)
├── confidence.py       (13K — 7-signal scoring, BUG: bool .get())
├── books.py            (18K — CRUD, file management)
├── intelligence.py     (16K — admin views, bulk operations)
├── db.py               (2.3K — asyncpg pool, fetch_one/fetch_all/execute)
├── routes/             (18 routers, ~8K total)
└── sources/            (20 adapters, one per external API)
```
