# Response to round-3 review (2026-09-30)

Response to [`2026-09-30-pr2-review-round3.md`](./2026-09-30-pr2-review-round3.md). All three blockers
and the actionable majors are fixed in the commit that follows this doc. The review was accurate,
including the two places it corrected me (Starlette matches first-registered, not last; the stub
loops report false success).

## Blockers

| # | Blocker | Fix |
|---|---|---|
| 1 | UNIQUE index on `book_files.original_sha256` + plain INSERTs → duplicate imports fail halfway (orphan book + stranded file; 190/399 fides pairs byte-identical) | Migration 014 index made **non-unique**. Both ingest paths now **look the hash up first** and skip cleanly: `watcher._import_file` hashes *before* the move and returns without creating anything (removing the incoming file so it isn't re-detected); `books._ingest_one_file` checks after capturing hashes and returns `{"warning":"already_in_library","existing_book":…}`, unlinking the uploaded temp. New shared helper `watcher._fetch_existing_by_hash`. |
| 2 | `triage` / `verify` routers never mounted → every call 404s | `web.py` now imports and `include_router`s both (`/api/v1/triage/*`, `/api/v1/verify/*`). Verified both define `router` and `import brainycat.web` succeeds. |
| 3 | `deploy-moba-windows.ps1` publishes SSH topology (IPs, root logins, port 2222) in a public repo | **Removed from the branch** (`git rm`) and added to `.gitignore` so it can't be re-committed from the WIP tree. `ebooks_wished_for.md` (personal, unrelated) also removed + ignored. |

> On blocker 3's history note: `a4acda0` already landed the script on the public branch. If the owner
> wants it gone from history (not just from the tip), the branch would need a rewrite before merge —
> flagged for the owner; not done here because the branch is shared and force-pushing it is the
> owner's call.

## Majors

| # | Major | Fix |
|---|---|---|
| 4 | Re-enabled loops call stubs that return zero and look healthy | Only the **real** modules stay scheduled — `validation` (metadata_validator, 173 lines) and `confidence` (324 lines). `cover_phash`, `ocr_copyright`, `incipit_match` are 5-line stubs → **unscheduled**, and their functions now **raise `NotImplementedError`** so nothing can report success for them. `incipit_match` (which was scheduled on `main`) removed from the loop list. |
| 5 | K4 only partly fixed; docstrings had the rule backwards | Found the **third** `/import/goodreads` (JSON body, ~line 1201) and a **fourth** `import_calibre` function name (line ~1432) — both missed earlier. Goodreads JSON handler → `/import/goodreads/json`; the fourth calibre function renamed to `import_calibre_library_full`. **ruff F811 on admin.py now passes clean.** Corrected the docstrings: Starlette matches **first-registered**, so the earlier handler was live and the renamed ones were the dead ones. |
| 6 | Unwired modules + lint regression | `watchword.py` / `mass_convert.py` / `ocr_scan.py` are landed but **unwired** (noted here and in the reconciliation report). Auto-fixed the safe ruff findings in the new modules; the remainder (mostly `T201 print` in the CLI-ish helpers and annotations) are left for **K15** rather than risk-editing modules this PR didn't author. |
| 7 | D1 details | Acknowledged: skeleton compare is still `==` (fuzzy match is a later dedup task), and the cursor is a positional index into a title-sorted list (a keyset cursor would be exact). Left as the review rates them — minor; the re-scan regression itself is fixed. |

## Verification

- `import brainycat.web` / `scheduler` / `watcher` / `books` all succeed.
- `ruff check brainycat/routes/admin.py --select F811` → clean.
- **280 unit tests pass** (the pre-existing `test_calibre.py` / `test_epub_check.py` collection errors remain, unclaimed).
- No build artifacts committed; `deploy-moba-windows.ps1` / `ebooks_wished_for.md` removed.

## On the two loops the review couldn't vet (validation, confidence)
Both are now scheduled and do real DB work. They were **not** independently audited for correctness in
this PR either. If the reviewer prefers, they can stay **unscheduled** until their logic is reviewed —
say the word and I'll drop them from the loop list (the modules remain, just not auto-run). The
process-split suggestion (planning docs / P0+012-013 / 014+hashing / UI / unwired modules as separate
PRs) is sound; this PR keeps them together per the owner's "same PR" instruction, with the reviewer
getting the last word.
