# WIP Reconciliation Report (2026-09-30)

> Records how the author's uncommitted working-tree files were reconciled against `main` after the
> fides session commit (`f02f7cf`, "session work 2026-09-28/30") landed. Per owner instruction:
> commit genuinely-new modules, reconcile overlapping files individually, and let the PR reviewer
> get the last word. This PR brings in the **new modules** and the **known-issue fixes**; the 17
> overlapping files are **held** (not committed) with the reasons below.

## Brought in (new, non-conflicting)

These did not exist in `main`, so there is no conflict. They are what let the four disabled scheduler
loops be re-enabled.

| File(s) | Purpose | Now used by |
|---|---|---|
| `brainycat/confidence.py` | Batch confidence scoring (`compute_batch`, `compute_confidence`) | re-enabled `confidence` scheduler loop; `/intelligence` |
| `brainycat/cover_phash.py` | Cover perceptual hashing (`process_batch`) | re-enabled `cover_phash` loop; dedup signal (D2) |
| `brainycat/metadata_validator.py` | Validate enriched metadata vs content (`validate_batch`) | re-enabled `validation` loop |
| `brainycat/ocr_copyright.py` | OCR copyright/credits page for ISBN (`process_batch`) | re-enabled `ocr_copyright` loop |
| `brainycat/text_profiler.py` | Text profiling helper (`process_batch`, checkpointed) | available; fingerprint loop already covers dedup |
| `brainycat/incipit.py`, `incipit_match.py` | Opening-text dedup + ISBN propagation | `incipit_match` loop (already scheduled) |
| `brainycat/ocr_scan.py`, `mass_convert.py`, `watchword.py` | OCR scan, bulk convert, watchword helpers | ad-hoc / future wiring |
| `brainycat/routes/triage.py`, `routes/verify.py` | Triage + verification admin routes | `static/triage.html`, `static/verify.html` |
| `static/triage.html`, `static/verify.html` | Their UIs | — |
| `scripts/audit_dedup_coverage.py`, `bnf_indexer.py`, `ol_indexer.py` | Ops scripts | manual runs |
| `devdocs/` | Developer wiki (13 docs) | referenced by onboarding.md |
| `ebooks_wished_for.md`, `deploy-moba-windows.ps1` | Wishlist, Windows deploy helper | — |

Build artifacts were **git-ignored, not committed**: `ebook-convert-rs/target/`, `BClocal`,
`reports/`.

## Held (overlapping — would regress `main`; reviewer to decide file-by-file)

All 17 of these were modified in the author's tree **before** the fides session commit and now
**conflict with, and would revert,** the work that just landed on `main` (`f02f7cf`, and PR #1). They
are a stale pre-fides fork, not an improvement over current `main`, so they are **not** included here.

**Proof (representative):** the local `brainycat/isbn.py` *removes*
`from brainycat.identify import decide, filename_isbn` and the `settings` import — but current `main`'s
`extract_and_store_isbn()` depends on `decide()` / `filename_isbn()`. Applying the local version would
break the identification pipeline. `f02f7cf` also directly modified `books.py`, `conversion.py`,
`isbn.py`, `rate_limit.py`, `routes/books.py`, `sources/google_books.py`, `sources/open_library.py`,
`web.py` and `static/reader.html` — the same files the local tree changed.

| File | Local diff vs main | Overlaps fides `f02f7cf`? | Disposition |
|---|---|---|---|
| `brainycat/isbn.py` | +161/-110 | yes (+ removes deps main needs) | hold — stale fork; would break identification |
| `brainycat/rate_limit.py` | +192/-90 | yes | hold |
| `brainycat/routes/books.py` | +116/-174 | yes (fides +101) | hold |
| `brainycat/books.py` | +101/-153 | yes | hold |
| `brainycat/conversion.py` | +44/-52 | yes | hold |
| `brainycat/sources/google_books.py` | +61/-30 | yes (fides +14) | hold |
| `brainycat/sources/open_library.py` | +43/-4 | yes | hold |
| `brainycat/web.py` | +43/-24 | yes | hold |
| `static/reader.html` | +25/-66 | yes (fides +59) | hold |
| `brainycat/sources/oclc.py` | +1/-1 | no | trivial; reviewer may cherry-pick |
| `brainycat/series_detect.py` | +7/-7 | (K2 fixed here directly on main's version) | superseded by the K2 fix in this PR |
| `README.md`, `docs/honest-status.md`, `docs/launch-plan.md`, `docs/roadmap.md`, `docs/selfhosted-post.md` | doc drift | partial | hold — docs re-graded separately in this PR |
| `.gitignore` | +2/-3 | — | superseded by the artifact-ignore commit here |

**Recommendation for the reviewer:** treat the 17 held files as a separate, later cherry-pick pass —
diff each hunk against current `main` and take only hunks that add something `f02f7cf` didn't already
land. Do **not** apply them wholesale (guaranteed regression). The author's tree remains the source of
truth for them; nothing was discarded.
