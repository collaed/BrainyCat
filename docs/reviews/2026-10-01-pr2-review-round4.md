# Review, round 4 — the round-3 fixes (PR #2)

> Covers `2f5291b` and its response doc
> ([`2026-09-30-pr2-review-round3-response.md`](./2026-09-30-pr2-review-round3-response.md)). Every claim
> was checked against the code at `2f5291b`. The unit tests ran in an isolated container, and the route
> table was inspected by importing `brainycat.web`. Lint counts compare against committed `origin/main`.

## Summary

The round-3 fixes are real:
- **Blocker 1 (the regression) is fixed.** Migration 014's index is now non-unique. Both ingest paths
  look the hash up before inserting anything, and the watcher hashes before the move, so neither path
  can leave an orphan row or a stranded file any more.
- **Blocker 2 is fixed.** Both routers are mounted, and `/api/v1/triage/*` and `/api/v1/verify/*`
  resolve.
- **Blocker 3 is fixed at the tip.** See the history note below.
- **The stubs are handled.** The three stub loops are unscheduled and now raise
  `NotImplementedError`. Nothing else calls them.
- **K4 is fixed for the import routes.** The route table no longer has duplicate
  `POST /import/goodreads` or `POST /import/calibre` entries, and ruff F811 is clean on `admin.py`.
- **Lint is down to +36 findings** against `origin/main` (130 → 166), from +43 in round 3.
- **Tests:** 280 unit tests pass. The same two long-standing collection errors remain.

One new behaviour needs to change before merge (finding 1), and one new endpoint is broken
(finding 2). The rest are small.

## Findings

### 1. Should fix before merge: the watcher now silently deletes duplicate files from incoming
`watcher._import_file` calls `os.remove(file_path)` when the hash matches a file already in the library
(`brainycat/watcher.py:121`). Today on `main`, the same file is imported as a duplicate book, so nothing
is lost. With this PR:
- **The deletion can't be undone, and only a log line records it.** There is no trace in the UI.
- **The original filename is lost.** The owner has said original names carry information; that's why
  unresolved titles are no longer renamed.
- **It contradicts the owner's call on the incoming folder.** They asked for non-importable files to
  stay there and be browsable (that browser is built on `main`, not yet committed).

The bytes themselves aren't lost: deleting a book cascades to its `book_files` rows, so a hash match
does mean the library holds that file. That's why this is "should fix" and not a blocker.

**Fix:** move the file to `incoming/duplicates/<name>` instead of deleting it, and log the existing
book id. The watcher only scans top-level files, so the subfolder is never re-imported. As a cheap
safety check, treat the match as a duplicate only if the matched book's file still exists on disk.

**Related, for the owner's incoming browser:** its "Import now" action calls `watcher._import_file`,
which returns `None` whether it imported the file or skipped it. Once this PR is merged, clicking
Import on a duplicate would report success while the file disappears. Please have `_import_file`
return a status, for example `{"imported": book_id}` or `{"duplicate_of": book_id}`. The browser
route will be adapted to use it.

### 2. Bug: `GET /api/v1/verify/stats` returns 500, and the verify page calls it on every load
In `routes/verify.py`, `@router.get("/{book_id}")` (line 28) is registered before
`@router.get("/stats")` (line 49). Starlette matches the first registered route, so `/stats` reaches
`book_confidence("stats")`, and `UUID("stats")` raises `ValueError`. Checked against the route table:
`/api/v1/verify/stats -> book_confidence`. `static/verify.html` calls `loadStats()` on page load.

**Fix:** move `/stats` above `/{book_id}`, or declare `book_id: UUID` so a non-UUID path doesn't match.

### 3. Propose: one route-table test to close K4
A unit test over `app.routes` would catch finding 2 and every remaining duplicate. It should assert
two things:
- no two routes share the same method and path;
- no literal path is registered after a `{param}` sibling it would collide with.

It would also catch six duplicates that already exist on `main`. They're pre-existing, not caused by
this PR, but they're the same K4 class:

| Method and path | Handlers (first registered wins) |
|---|---|
| `POST /api/v1/collections` | `create_collection` ×2 |
| `GET /api/v1/collections` | `list_collections` ×2 |
| `DELETE /api/v1/collections/{collection_id}/books/{book_id}` | `remove_book_from_collection`, `remove_from_collection` |
| `GET` and `POST /api/v1/challenges` | `get_challenges_list` / `create_challenge_endpoint`, then `list_challenges` / `create_challenge` |
| `POST /api/v1/import/kindle-clippings` | `import_kindle`, `import_kindle_clippings` |
| `GET /compat/abs/api/items/{item_id}/cover` | `abs_cover`, `abs_item_cover` |

### 4. Your question about the validation and confidence loops: keep them scheduled
They're now audited:
- **No external calls.** Neither module (nor `compute_confidence` and its helpers) makes network calls.
- **Narrow writes.** Each writes only its own `extra_metadata` keys: `confidence_score`,
  `confidence_conflicts`, and `validation`. Titles, ISBNs, and files are never touched.
- **No more `jsonb_set` crash.** Migration 013 repairs array-valued rows and adds the CHECK, which
  removes the crash `fast_local` had.

One small fix: `confidence.compute_batch` has no per-book `try/except`, and its order is fixed
(`ORDER BY quality_score DESC`). A single book that raises therefore fails the whole batch every
60 seconds, forever: the same "re-scan the first batch" failure D1 had. `validate_batch` does catch
errors per book, but it doesn't mark failures, so up to 10 failing books at the top would stall it
the same way. Catch errors per book, and record the failure (for example in `book_pipeline_state`)
so a failed book is skipped next time.

### 5. Minor: the hash guard only covers files imported after migration 014
`original_sha256` is NULL for every book already in the library (about 3,900 on the reference
library), and nothing backfills it. So re-dropping a file the library already holds still creates a
duplicate. That isn't a regression; it's how `main` behaves today. A backfill could:
- compute `current_sha256` for every stored file;
- have the guard match `original_sha256 = $1 OR current_sha256 = $1`. For PDFs, and for EPUBs that
  `fix_epub` left alone, the stored bytes are the original bytes.

### 6. Minor: the duplicate guard has no test
The project's convention is a failing test that reproduces the bug, then green. Two small unit tests
with `fetch_one` mocked would cover it:
- **Watcher:** a matching hash produces no `INSERT` and the file is moved, not left in place.
- **Upload:** a matching hash returns `already_in_library` and doesn't insert.

### 7. Nit: the upload path leaves an empty folder behind
On an `already_in_library` return, the caller's `/data/books/<uuid>/` folder is left empty. The older
`likely_duplicate` early return (from before this PR) is worse: it leaves the uploaded file itself
behind. Both could share one cleanup.

## The SSH script in history
`deploy-moba-windows.ps1` (still reachable at `a4acda0`) reads private keys from a separate secrets
file at run time. It contains no keys or passwords of its own; what it exposes is topology: hosts,
users, and the port. Rewriting history isn't worth it: GitHub keeps the PR's commits under
`refs/pull/2/head` regardless, and squash-merging the PR keeps them out of `main`. Treat the topology
as public instead: key-only SSH, with no password login for root.

## Correction to round 1
Round 1 said `contribute.contribute_back` "submits metadata to Open Library". **That was wrong.**
Today it's a dry run: it reads Open Library by ISBN and records `can_contribute_to_ol`, and nothing is
submitted (`docs/features.md` says so too). The round-1 doc now carries a correction note.
`docs/roadmap/decisions-and-code.md:207` repeats the claim and should say "will submit, once R2.11.18
is built". Gating `contribute_back` for summaries is still right, but it's future-proofing, not a
current leak. So `POST /api/v1/verify/{id}/confirm` calling it is harmless today.

## Merge readiness
Merge after findings 1 and 2. Findings 3–7 can follow as backlog items (3 closes K4; 4 and 5 belong
with M1 / `book_pipeline_state`). Keeping one PR is fine given the owner's choice; squash-merge it.
