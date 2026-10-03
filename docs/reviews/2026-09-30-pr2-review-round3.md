# Review, round 3 — the code update (PR #2)

> Covers the commits after round 2 — `79e1f0b` (merge of `main`), `c0ebc75` (K2), and `a4acda0`
> (K3/K4/K6/D1/M1/M2 fixes, four re-enabled loops, new modules, migrations 012–014, triage and verify
> pages, `devdocs/`). As before, every claim was checked against the code, the fides database, and
> test runs. The PR's unit tests were run in an isolated container that never touched the fides
> database.

## Summary

Good progress, and several of the fixes are exactly right:
- **Migration 012 now matches the code:** status `library`, `reading_log.minutes` / `logged_at`, a
  nullable `book_id`, and no unique constraint. This is the P0 fix working as intended.
- **Migration 013 is correct:** it repairs non-object rows first, then adds a guarded CHECK
  (idempotent).
- **K2 is fixed correctly:** `series_index` is now set on `books`.
- **K6 hashing order is right:** `watcher._import_file` hashes the original bytes after the move and
  before `fix_epub`, and `books._ingest_one_file` does the same.
- **D1:** a persisted cursor now sweeps the whole list, and the size ratio is finally used.
- **Tests:** 280 unit tests pass (the long-standing `test_calibre.py` / `test_epub_check.py`
  collection errors remain; they aren't claimed as fixed). `devdocs/` has landed.

Three things should block merging, and a few more need fixing before the code is trustworthy.

## Blockers

### 1. Migration 014's unique index makes ordinary duplicate imports fail halfway
`book_files_original_sha256_uidx` is `UNIQUE`, but both ingest paths do a plain
`INSERT INTO book_files (…, original_sha256, …)` with no conflict handling. In
`watcher._import_file` the order is: move the file into `/data/books/<uuid>/`, then
`INSERT INTO books`, then `INSERT INTO book_files`. When a byte-identical file arrives a second time:
- the `book_files` insert raises `UniqueViolationError`;
- the `books` row is left without a file, and the moved file is stranded in its new folder;
- the exception aborts the watcher pass.

This is not hypothetical. On fides, **190 of 399** same-size file pairs checked are byte-identical,
so the library already holds many exact copies. The same collision also breaks any backfill of the
new column.

Suggested fix: make the index non-unique for now, and handle "exact duplicate" explicitly at ingest.
Look up the hash first; if found, skip the import and report "already in library as ⟨book⟩" (the
Incoming-folder view being added on `main` can show it). Make it unique only when multi-user lands, together
with `ingest_dedup`'s membership/virtual-copy path and an `ON CONFLICT` branch.

### 2. The new triage and verify pages can't work: their routers aren't mounted
`routes/triage.py` and `routes/verify.py` define routers, but `web.py` (unchanged in this PR) never
imports or `include_router`s them. Every `/api/v1/triage/*` and `/api/v1/verify/*` call from
`static/triage.html` and `static/verify.html` returns 404.

### 3. `deploy-moba-windows.ps1` publishes the owner's SSH setup in a public repo
It has no private keys, but it lists server IPs (`178.104.101.76`, `178.104.123.117`,
`test.clubcep.eu`), **root** logins, an extra SSH service on port 2222, and key file names. That is
free reconnaissance for anyone scanning GitHub, and it isn't BrainyCat code. Remove it from the PR.
Because commit `a4acda0` is already public on the branch, the owner may also want to:
- rewrite the branch before merging, so it never lands in `main`'s history;
- check that root SSH is key-only (it appears to be) or disabled.

`ebooks_wished_for.md` at the repo root is lower-stakes, but it is also personal and unrelated to
the code; move it out, or into `docs/examples/` if it's meant as test data for "Get a book".

## Major

### 4. Re-enabled loops call stubs that do nothing and report success
`cover_phash.py` and `ocr_copyright.py` are 5-line stubs that return zero counts, and
`incipit_match.py` is the same. The scheduler comment says each module "exposes the function its
loop calls". That's true, but the loops now run every 15–30 s, do nothing, and look healthy. Once
the M10 heartbeat lands, they will show as green while the features don't exist. That goes against
the CLAUDE.md convention that a job must not report success for work it didn't do. Either leave them
unscheduled until they are implemented, or make the stubs raise `NotImplementedError`, so that
`_supervised` and the heartbeat report them as not working.

### 5. K4 is only partly fixed
- **`POST /import/goodreads` is still registered twice.** `import_gr` (multipart, line 45) and
  `import_goodreads` (JSON body, line 1201) share the path, so the second remains unreachable. ruff
  still reports F811 for `import_goodreads` and `import_calibre`.
- **The new docstrings have the rule backwards.** They say FastAPI uses the last-registered route
  for a duplicate path; Starlette actually matches in registration order, so the **first** route
  wins. That means the handlers moved to `/import/calibre/import` and `/import/goodreads/csv` are
  the ones that had been dead.
- **No page calls either path**, so the rename breaks nothing.

### 6. New modules with no callers, and a lint regression
- **Unwired modules.** `watchword.py`, `mass_convert.py` and `ocr_scan.py` are imported nowhere
  (not by the scheduler, routes, scripts or pages). Fine to land as part of L1, but the backlog
  should say they are unwired.
- **Lint regression.** The branch has **121** ruff findings versus **78** on `main`, mostly in these
  new modules (`watchword.py` alone has 22). That adds to K15 rather than reducing it.

### 7. D1 details (minor)
- The skeleton comparison is still an exact `==`; the fuzzy match from the plan isn't there yet.
- The cursor is an index into a title-sorted list that shifts as books are added or removed. That's
  acceptable for a sweep, but a keyset cursor (the last title/id seen) would be exact.

## Process suggestion

The PR now mixes planning docs, production code, migrations and personal tooling (~8,000 lines).
Consider splitting it:
1. planning and review docs (reviewed; can merge);
2. the P0 fixes plus migrations 012–013 (small and safe);
3. migration 014, hashing and pipeline state, with blocker 1 fixed;
4. the triage/verify UI once mounted;
5. unwired modules as a separate "land L1" PR.

Each can then be reviewed and deployed on its own, and blocker 3 never reaches `main`.
