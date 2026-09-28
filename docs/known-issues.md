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
