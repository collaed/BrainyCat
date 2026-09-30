# Deployment

## Where It Runs

BrainyCat runs on **sake** (home server). Not ecb.pm. Not "the cloud."

```
sake
├── brainycat         (container, port 8000, up 29h)
├── brainycat-db      (PostgreSQL 16, healthy, up 4 days)
├── intello           (container, port 8000 internal, on same Docker network)
├── prowlarr          (port 9696)
├── readarr           (port 8787)
└── flaresolverr      (port 8191)
```

## Access Paths

| Path | Status | Notes |
|------|--------|-------|
| `sake:8000` (LAN direct) | ✅ Working | Primary access method |
| `tools.ecb.pm/brainycat/` | ❌ BROKEN | Caddy on ecb.pm proxies to `brainycat:8000` via Docker DNS — but there's no brainycat container on ecb.pm |
| `books.ecb.pm` | ❌ DOES NOT EXIST | No such subdomain or Caddy site |

### Why ecb.pm Access Is Broken

The Caddy config on ecb.pm (`/opt/caddy/sites/tools.caddy`) has:

```caddy
handle_path /brainycat/* {
    request_body { max_size 500MB }
    reverse_proxy brainycat:8000
}
```

This expects a Docker container named `brainycat` on the same Docker network as Caddy — **on ecb.pm itself**. But the container only exists on sake. Caddy can't resolve `brainycat` via Docker DNS → connection refused → 502.

### Fix Options

1. **Change upstream to sake's IP** — `reverse_proxy 192.168.x.x:8000` (requires sake to be reachable from ecb.pm, may not work if they're on different networks)
2. **SSH tunnel/WireGuard** — tunnel from ecb.pm to sake:8000
3. **Move brainycat to ecb.pm** — deploy the container on the VPS instead
4. **Accept LAN-only** — just use sake:8000 directly

The API routes (`/brainycat/api/*`) and public routes (`/brainycat/public/*`) are also broken for the same reason.

## Docker Compose

### Production (with existing PostgreSQL)

`docker-compose.yml`:
```yaml
services:
  brainycat:
    build: .
    container_name: brainycat
    restart: unless-stopped
    networks: [web, db]
    expose: ["8000"]
    env_file: [.env]
    volumes:
      - brainycat-data:/data
      - ./brainycat:/app/brainycat    # live code mount
      - ./static:/app/static          # live frontend mount
    entrypoint: >
      sh -c "for i in 1 2 3 4 5; do alembic upgrade head && break || sleep 3; done;
             uvicorn brainycat.web:app --host 0.0.0.0 --port 8000"
```

Code is volume-mounted, so `docker restart brainycat` picks up code changes without rebuild.

### Standalone (includes PostgreSQL)

`docker-compose.standalone.yml` — adds a `pgvector/pgvector:pg16` container with healthcheck. For fresh installs.

## Environment Variables

Current `.env` on sake:
```
BRAINYCAT_DATABASE_URL=postgresql://brainycat:brainycat@postgres:5432/brainycat
BRAINYCAT_SECRET_KEY=change-me-in-production
BRAINYCAT_DATA_DIR=/data/books
BRAINYCAT_INCOMING_DIR=/data/incoming
BRAINYCAT_INTELLO_URL=http://intello:8000
BRAINYCAT_SIGNAL_API_URL=http://signal-api:8080
BRAINYCAT_SMTP_HOST=mailserver
BRAINYCAT_SMTP_PORT=587
```

### Required

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | (must set) | PostgreSQL connection |
| `SECRET_KEY` | auto-generated | JWT signing; auto-persisted to `/data/.secret_key` if empty |

### Directories

| Variable | Default |
|----------|---------|
| `DATA_DIR` | `/data/books` |
| `INCOMING_DIR` | `/data/incoming` |

### Optional Services

| Variable | Purpose | Current state |
|----------|---------|---------------|
| `INTELLO_URL` | AI server (TTS, OCR, LLM, lookup) | Set to `http://intello:8000` — reachable on Docker network but enrichment still times out |
| `SMTP_HOST` | Kindle delivery | Set but untested |
| `SIGNAL_API_URL` | Push notifications | Set but untested |
| `GOOGLE_BOOKS_API_KEY` | Higher API quota | Not set |
| `OFFLINE_LOOKUP` | Download OL/BnF dumps | Not explicitly set (bootstrap has already run) |

### Feature Flags

| Variable | Default | Notes |
|----------|---------|-------|
| `ENABLE_FTS` | true | Full-text content indexing |
| `ENABLE_EMAIL_IMPORT` | false | IMAP inbox monitoring |
| `EXP_TEXT_PROFILE` | false | Incipit + fingerprint extraction |
| `EXP_LSH_DEDUP` | false | LSH-based duplicate detection |

## Dockerfile

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg sox espeak-ng calibre libzbar0 wget fonts-dejavu-core
RUN pip install piper-tts
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
WORKDIR /app
RUN mkdir -p /data/books /data/incoming
EXPOSE 8000
```

Image is ~1.2GB (Calibre alone is ~400MB).

## Migrations

Alembic, auto-run on container startup. 5 migration files:

```
migrations/versions/
├── 001_initial_schema.py          # 25+ tables, extensions, triggers
├── 002_add_missing_tables.py      # enrichment_log, fingerprints, duplicate_matches
├── 003_filename_history.py        # filename change tracking
├── 004_metadata_operations_log.py # metadata audit trail
└── 005_content_index_and_rules.py # FTS content index + consumption rules
```

Extensions created: `pgvector`, `pg_trgm`, `unaccent`.

## Backup

```bash
# Database dump
ssh sake "docker exec brainycat-db pg_dump -U brainycat brainycat | gzip > /tmp/bc_$(date +%Y%m%d).sql.gz"

# API endpoint
POST /api/v1/backup → gzipped CSV

# Files
# brainycat-data volume contains:
# /data/books/          Book files (Genre/Author/Title)
# /data/incoming/       Watch folder
# /data/isbn_lookup.db  OL SQLite index (2-4GB, regeneratable)
# /data/bnf_lookup.db   BnF SQLite index (500MB, regeneratable)
# /data/.secret_key     JWT secret
```

The SQLite databases are regeneratable from public dumps — don't need backup.

## Useful Commands

```bash
# Container status
ssh sake "docker ps --filter name=brainycat"

# Restart (picks up code changes)
ssh sake "docker restart brainycat"

# DB shell
ssh sake "docker exec -it brainycat-db psql -U brainycat brainycat"

# Enrichment stats
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT method, success, COUNT(*) FROM enrichment_log
  WHERE created_at > now() - interval '24 hours'
  GROUP BY method, success ORDER BY count DESC;\""

# Quality distribution
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT quality_score/10*10 as bracket, COUNT(*)
  FROM books GROUP BY 1 ORDER BY 1;\""

# Check for stuck queries
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT pid, state, query_start, left(query, 80) FROM pg_stat_activity
  WHERE datname='brainycat' AND state != 'idle';\""
```
