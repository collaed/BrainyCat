# Known Issues

Engineering-level bugs that are tracked but not yet fixed — distinct from `docs/roadmap.md` (new
features) and the in-app "Flag as suspicious" mechanism (per-book metadata disputes, see
`metadata-ops.html` / `brainycat/metadata_audit.py`, which only makes sense for a specific book's
field change, not a codebase bug like these).

## ebook-convert-rs (Rust converter)

Added 2026-09-28. Now the primary converter (`brainycat/conversion.py::convert()`), falling back to
Calibre's `ebook-convert` only when the binary is missing or a specific run fails — see that file's
`_ebook_convert_rs()` for the up-to-date fallback logic and diagnostic logging (every failure logs
full `stderr`/`stdout`/return code at WARNING level; search Docker logs for `conversion_rs_failed`).

- **HTML entities not decoded in output text.** Converting an EPUB whose source HTML contains
  entities like `&amp;` passes them through literally into the output instead of decoding to `&`.
  Reproduced converting book `3bee02b8-756f-4756-aa46-3bc2eddd49ec` ("Domination & Submission: The
  BDSM Relationship Handbook") EPUB→PDF: page 1 text reads `DOMINATION &amp; SUBMISSION` instead of
  `DOMINATION & SUBMISSION`. Likely in the HTML/XHTML text-extraction step of the OEB pipeline
  (`ebook-convert-rs/src/pipeline/`) — text nodes are being taken as raw markup source rather
  than parsed/unescaped.
- **Character-encoding mojibake (double-encoded UTF-8).** Same reproduction: `COPYRIGHT © 2013`
  renders as `COPYRIGHT Â© 2013` in the converted output — the classic symptom of UTF-8 bytes being
  read as Latin-1 (or similarly re-encoded) somewhere in the pipeline. Needs a source-encoding audit
  in the input parsing stage (`ebook-convert-rs/src/formats/`) — check where file bytes are
  first decoded to Rust `String`/`str` and whether an explicit UTF-8 decode is happening once, or the
  encoding is being inferred/applied more than once across the pipeline.

Both were found via the same test conversion, so likely share a root cause (a text-decoding step that
runs at the wrong layer or runs twice). Not yet reproduced against a matrix of other real books —
next investigation step is probably to grep the pipeline for anywhere `String::from_utf8`,
`.to_string()` on raw bytes, or manual entity handling happens, and confirm it's exactly once, in the
right place, on the right byte source.

## `books.original_filename` / `book_originals` — never existed, several call sites assumed otherwise

Not a single bug — a recurring assumption across several independently-written modules that a
denormalized `books.original_filename` column (or a whole `book_originals` table, with
`original_title`/`original_filename`) exists. Neither ever landed in a migration. Every call site
that referenced them crashed outright (`UndefinedColumnError`/`UndefinedTableError`) or, worse, was
silently caught and retried forever by an outer `except Exception` (found `brainycat.scheduler`'s
`_isbn_worker` background threads doing this — crash-loop-sleep(10s) since the code was deployed,
with zero useful work done).

Fixed by using the real source: `book_files.file_name` (set at upload) in place of
`original_filename` (`brainycat/isbn.py::extract_and_store_isbn`,
`brainycat/scheduler.py::_isbn_worker`), and the earliest `metadata_history` title-change row as a
proxy for `original_title` where drift-detection needs "the title this book started with"
(`brainycat/metadata_audit.py::check_drift`/`find_drifted_books`) — real data now that
`record_change()` is actually called with the true prior value (see the `metadata_history` fix in
the "upload/OPDS/auth" PR). If another `original_filename`/`book_originals` reference turns up, it's
the same root cause — apply the same substitution, don't add the phantom column/table.

## Four scheduler loops call modules that were never implemented

`brainycat/scheduler.py::start_scheduler` registered five background loops
(`_text_profiler_loop`, `_ocr_copyright_loop`, `_cover_phash_loop`, `_validation_loop`,
`_confidence_loop`) that each `import` a module that was never written:
`brainycat.text_profiler`, `brainycat.ocr_copyright`, `brainycat.cover_phash`,
`brainycat.metadata_validator`, `brainycat.confidence`. Every tick (10s/15s/30s/30s/60s
respectively) they hit `ModuleNotFoundError`, got caught by `_supervised()`'s outer
`except Exception`, and logged a `*_error` warning forever.

**Correction, found later the same session:** `_text_profiler_loop` was initially lumped in with
the other four and disabled — wrong call. Its body wasn't *only* the missing-module import; below
that it also called `brainycat.fingerprints.find_duplicates_by_content()`, which is a real,
working function (drives the Content Duplicates page, `static/intel-content-dupes.html`). This
loop was the *only* thing that ever called it (and `compute_all_fingerprints()`) automatically —
so disabling the loop silently stopped a working feature, not just a broken stub. Fixed by
rewriting it as `_fingerprint_loop`, calling `compute_all_fingerprints()` +
`find_duplicates_by_content()` directly instead of the nonexistent `text_profiler.process_batch()`,
and re-scheduling it (20s interval). Lesson: when a loop body has multiple statements, check each
one before writing off the whole loop as dead.

The remaining four are disabled by removing their entries from the `loops` list in
`start_scheduler()` (the function bodies are left in place as a starting point). What each was
meant to do, if picked up later:

- **ocr_copyright** — scan OCR'd text for a copyright page / rights statement, presumably to flag
  books that shouldn't be OCR'd or re-distributed.
- **cover_phash** — perceptual hash of cover images, for duplicate/edition detection independent
  of text similarity.
- **metadata_validator** — a validation pass over enriched metadata (referenced nowhere else, no
  spec found).
- **confidence** — batch confidence scoring (`brainycat/identify.py`'s `resolve()`/`decide()` may
  already cover this ground for ISBN identification specifically — check there before building a
  separate `confidence.py`).

`brainycat.ol_local` (referenced by `brainycat/fast_local.py` and `brainycat/ol_works.py`) was the
sixth missing module in this family but is being built for real (local Open Library dump import —
see the OL-dump import task) rather than silenced, since `fast_local_isbn`/`fast_local_title` are
still scheduled and useful once it exists.

## `books.extra_metadata` sometimes degrades from a JSON object into a JSON array

Found on 5 books while verifying the new `ol_local` wiring (`fast_local_isbn_error: "path element
at position 1 is not an integer: \"title_parsed\""`) — `jsonb_set(..., '{local_enriched}', ...)`
requires an object target, but `extra_metadata` on these rows is a JSON **array** whose elements
include both proper objects (`{"title_fixed": true}`) and, oddly, JSON-encoded **strings**
(`"{\"isbn_ocr_tried\": true}"` — a string containing escaped JSON, not a parsed object).

Likely mechanism: Postgres's `jsonb || jsonb` concatenation operator requires *both* operands to be
objects to merge by key — if either side isn't an object, both sides get coerced into arrays and
concatenated element-wise instead. Several modules write via
`extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb` (`title_cleanup.py`,
`metadata.py`, `bisac.py`, `worddumb.py`, `contribute.py`, `readability.py`,
`routes/books.py`, `scheduler.py`) — if *any one* of these ever received a non-object payload for
`$1` (or ran against a row where `extra_metadata` had already been corrupted into an array by an
earlier bad write), the object silently mutates into an array from then on. Once that happens,
`extra_metadata ? 'some_flag'` (used everywhere as an "already processed" guard) checks array
*element* membership instead of object *key* membership, which never matches a flag stored as
`{"flag": true}` — so the "already processed" guard permanently fails open and the same background
loop reprocesses (and re-appends to) that book's `extra_metadata` forever, growing it without bound
(one affected book had ~80 duplicate `{"title_parsed": true}` array entries).

Not fully root-caused — haven't identified which specific call site first introduces a non-object
payload. `brainycat/fast_local.py`'s `jsonb_set` calls were patched to tolerate this (coerce back to
`{}` via `CASE WHEN jsonb_typeof(extra_metadata) = 'object' ...`) since that's the code path that
was actively crash-looping, but the other `||`-based call sites listed above are not yet hardened
and a currently-clean book could still be pushed into this state by any of them. Next step: audit
each `|| $N::jsonb` call site's Python-side payload to confirm it's always `json.dumps(<dict>)` (not
a list, not a double-encoded string), and consider a migration to clean up the already-corrupted
rows (`UPDATE books SET extra_metadata = '{}'::jsonb WHERE jsonb_typeof(extra_metadata) != 'object'`
after inspecting what — if anything — of value is recoverable from the affected rows' arrays).
