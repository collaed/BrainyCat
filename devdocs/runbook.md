# Operations Runbook

## Health Check (30 seconds)

```bash
# 1. Are containers running?
ssh sake "docker ps --filter name=brainycat --format '{{.Names}} {{.Status}}'"
# Expected: brainycat Up Xh, brainycat-db Up Xd (healthy)

# 2. Is the scheduler producing output?
ssh sake "docker logs brainycat --tail 20 2>&1 | grep -c 'fast_local_isbn'"
# Expected: >0 (the only loop reliably working)

# 3. Are there errors?
ssh sake "docker logs brainycat --tail 100 2>&1 | grep -c error"
# Expected: >0 (confidence_error fires every 60s, enrichment_timeout every 10s)
```

## Diagnostic Queries

```bash
# Quality distribution
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT quality_score/10*10 as bracket, COUNT(*)
  FROM books GROUP BY 1 ORDER BY 1;\""

# Enrichment throughput (last hour)
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT method, success, COUNT(*) FROM enrichment_log
  WHERE created_at > now() - interval '1 hour'
  GROUP BY method, success ORDER BY count DESC;\""

# Books still needing work
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT
    COUNT(*) FILTER (WHERE isbn IS NULL) as no_isbn,
    COUNT(*) FILTER (WHERE cover_path IS NULL) as no_cover,
    COUNT(*) FILTER (WHERE description IS NULL) as no_description,
    COUNT(*) FILTER (WHERE quality_score < 20) as quality_under_20
  FROM books;\""

# Stuck/long queries
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT pid, age(clock_timestamp(), query_start) as duration, state, left(query, 100)
  FROM pg_stat_activity WHERE datname='brainycat' AND state != 'idle'
  ORDER BY query_start;\""

# Rate limit state (which sources are backed off)
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  SELECT key, value FROM kv_store WHERE key LIKE 'ratelimit_%';\""
```

## Common Operations

### Restart BrainyCat

```bash
ssh sake "docker restart brainycat"
# Code is volume-mounted, so this picks up any code changes in ./brainycat/ or ./static/
# Alembic migrations run automatically on startup
```

### Apply a Code Fix

```bash
# Edit locally (code is in /home/collaed/BrainyCat/brainycat/)
# Then restart to pick up changes:
ssh sake "docker restart brainycat"

# Or if you're on sake directly:
cd /path/to/BrainyCat
# edit file
docker restart brainycat
```

### Force Re-enrichment of a Specific Book

```bash
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  UPDATE books SET quality_score = 0,
    extra_metadata = extra_metadata - 'enrich_attempts' - 'local_enriched'
  WHERE id = 'BOOK-UUID-HERE';\""
```

### Reset All Rate Limits

```bash
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  DELETE FROM kv_store WHERE key LIKE 'ratelimit_%';\""
ssh sake "docker restart brainycat"
```

### Clear Confidence Scores (force recompute)

```bash
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  UPDATE books SET extra_metadata = extra_metadata - 'confidence_score' - 'confidence_conflicts';\""
```

### Check Intello Connectivity

```bash
# From brainycat container (same Docker network)
ssh sake "docker exec brainycat curl -s -o /dev/null -w '%{http_code}' http://intello:8000/health"
# Expected: 200

# Test actual lookup
ssh sake "docker exec brainycat curl -s -X POST http://intello:8000/api/v1/lookup \
  -H 'Authorization: Bearer ecb2026' \
  -H 'Content-Type: application/json' \
  -d '{\"isbn\": \"9780134685991\", \"title\": \"Effective Java\"}' | head -c 500"
```

### Test External API Connectivity from sake

```bash
# Open Library
ssh sake "docker exec brainycat curl -s 'https://openlibrary.org/isbn/9780134685991.json' | head -c 200"

# Google Books
ssh sake "docker exec brainycat curl -s 'https://www.googleapis.com/books/v1/volumes?q=isbn:9780134685991' | head -c 200"

# Library of Congress
ssh sake "docker exec brainycat curl -s 'https://lx2.loc.gov/sru/lcdb?operation=searchRetrieve&query=bath.isbn=9780134685991' | head -c 200"
```

### Add Missing Indexes (fix statement_timeout)

```bash
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_books_quality ON books (quality_score);
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_books_isbn_null ON books (id) WHERE isbn IS NULL;
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_books_cover_null ON books (id) WHERE cover_path IS NULL;
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_books_no_local ON books (id) WHERE (extra_metadata->>'local_enriched') IS NULL;
\""
```

### Fix the Confidence Bool Bug

```bash
# Option A: Clean the bad data
ssh sake "docker exec brainycat-db psql -U brainycat -d brainycat -c \"
  UPDATE books SET extra_metadata = extra_metadata - 'local_title_tried'
  WHERE jsonb_typeof(extra_metadata->'local_title_tried') = 'boolean';
\""
# Converts 9,048 rows from boolean true to removed (null). The title loop will re-process them.

# Option B: Fix the code (add isinstance guard) — edit confidence.py line 131
```

### Database Backup

```bash
ssh sake "docker exec brainycat-db pg_dump -U brainycat brainycat | gzip > /tmp/brainycat_$(date +%Y%m%d).sql.gz"
ssh sake "ls -lh /tmp/brainycat_*.sql.gz"
```

## Monitoring Expectations

| Signal | Normal | Concerning | Broken |
|--------|--------|-----------|--------|
| fast_local_isbn logs/5min | 5-15 entries | 0-2 entries | 0 entries |
| enrichment_timeout/min | 0 (ideally) | 6/min (current) | — |
| confidence_error/min | 0 (ideally) | 1/min (current) | — |
| statement_timeout/hour | 0 | 1-5 | 10+ |
| Container uptime | Days | Hours (restarts) | Down |
| DB health | "healthy" | — | "unhealthy" |

## When Things Go Wrong

### "Everything timed out"
→ Check if PostgreSQL is overloaded (`pg_stat_activity`), if connections are exhausted, or if the asyncpg pool is full.

### "Container keeps restarting"
→ Check `docker logs brainycat --tail 100`. Usually a migration failure or import error at startup.

### "No enrichment progress for days"
→ Check rate limit state in `kv_store`. A source might be backed off for 6 hours after too many failures. Reset with `DELETE FROM kv_store WHERE key LIKE 'ratelimit_%'`.

### "Quality scores are wrong"
→ Quality is computed in `metadata.py` after enrichment based on field completeness. If fields are set but quality not updated, trigger a recompute:
```sql
-- Recompute quality for all books (expensive)
-- Better to let the scheduler handle this naturally
```
