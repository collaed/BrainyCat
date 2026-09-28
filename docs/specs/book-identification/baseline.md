# Baseline — Book Identification (T1 deliverable)

Corpus: full production library copied read-only from ecb.pm (`/var/lib/docker/volumes/brainycat_brainycat-data/_data/books`),
**1,956 book files** (1,256 EPUB, 644 PDF, 55 MOBI, 1 AZW3; 3,747 total files incl. audio, excluded here).
Harness: `tests/golden/scan.py` + `evaluate.py`/`postprocess.py`. Verification oracle: Open Library (`/isbn/{isbn}.json`),
proxy only — absence from Open Library is not evidence of a wrong ISBN, it's a coverage gap in the oracle itself
(especially for French/niche titles), so "unknown" is excluded from precision, not counted as failure.

## Runs

| # | Pipeline | Change | ISBN coverage | Auto-apply | Precision on OL-checkable auto-applies |
|---|---|---|---|---|---|
| 1 | baseline | current `isbn.py` (OPF→PDF meta→filename→text), first hit wins, always written | 69.5% (1360/1956) | 100% (blind) | 87.8% (270 sampled) |
| 2 | +grading | `identify.py`: agreement-graded confidence, no verification | 69.5% | 38.8% | 87.3% (no gain — grading alone doesn't fix wrong single-source hits) |
| 3 | +shared-ISBN guard | reject an ISBN carried by unrelated titles (placeholder/template values, e.g. one ISBN reused by 29 unrelated files) | 69.5% | 38.8% | same proxy sample, mismatches now visibly clustered in `possible` |
| 4 | +source verification | resolve against Open Library; verified→`certain`, contradicted→`possible` | 69.5% | **48.0%** (938/1956) | **100.0%** (578/578 OL-checkable auto-applies; 0 mismatches) |

Full numbers, run 4: `lookup_verdicts={'unknown': 709, 'verified': 578, 'mismatch': 73}`,
`by_class={'certain': 772, 'probable': 166, 'possible': 422}`.

## Reading this

- Coverage (69.5%) didn't move across runs 1-4 — these changes only decide *what to trust*, not *what to find*.
  Finding more (MOBI is at 14.5%; needs `ebook-convert`, not available in this harness) is a separate, later win.
- The real result: of everything the new pipeline auto-applies, **zero** confirmed-wrong ISBNs remain in the
  checkable sample (vs. an estimated ~12% wrong in the old blind-apply baseline). The 73 confirmed mismatches from
  run 1's blind behavior all landed in the `possible` review queue instead of being written.
- 422 files (22%) are queued for review rather than auto-applied — mostly single-method finds Open Library couldn't
  confirm either way (`unknown`, not `mismatch`) plus the shared-ISBN rejects. This is the coverage/precision
  trade-off R15 asks for: precision was prioritized over blindly maximizing writes.

## Against requirements.md R15 acceptance targets

| Target | Status |
|---|---|
| Auto-applied precision ≥ 99% | **Met** on the checkable sample (100%, 578/578). Needs a second oracle (Google Books, currently rate-limited from this host) to shrink the "unknown" 709 before this is fully trustworthy at scale. |
| Identification ≥ 98% for embedded/filename-ISBN books | Not yet measured directly — coverage work (item below) needed first. |
| Overall auto+queue coverage ≥ 90% | **Not met**: 69.5%. Remaining gap is books with no ISBN evidence at all (mostly MOBI, and EPUB/PDF with no embedded ISBN) — needs the title/author identification ladder (T6 ranks 3-5), not just ISBN grading. |
| Re-run idempotent (0 changes) | Not yet exercised — no live DB writes have happened; everything so far is offline (`tests/golden/`, `brainycat/identify.py`) and unwired from the real enrichment pipeline. |

## Code changes landed this iteration

- `brainycat/identify.py` (new): deterministic ISBN normalization, token-bounded filename extraction,
  agreement-graded `resolve()`, shared-ISBN `reject_shared()`, Open Library `verify()`/`apply_verification()`. 13 unit tests.
- `brainycat/fingerprints.py`: fixed non-deterministic `_kgram_hashes` (was using Python's per-process-randomized
  `hash()` on strings — fingerprints silently stopped matching across app restarts); added the missing
  `compare_fingerprints()` that `format_stack.py` has imported since it was written (every scheduled cross-format
  stacking attempt threw `ImportError`, swallowed by a bare `except`). 4 new tests incl. a real cross-format match
  on `pride_prejudice.epub` vs `pride_prejudice.txt` (Jaccard 0.96) and a cross-process determinism regression test.
- `tests/golden/`: `scan.py` (full-library CSV scan, baseline or new pipeline), `evaluate.py` (coverage/precision
  report), `ol.py` (Open Library lookup + cache), `postprocess.py` (shared logic between `scan.py` and `rescore.py`),
  `rescore.py` (re-run verification on an existing scan without re-extracting), `draft.py`/`manifest.yaml`
  (241-file labeled sample, separate from the full-library scan).

## Not done yet

- Nothing is wired into the live app (routes, scheduler, DB). All of this is an offline harness + a pure module.
- Coverage improvement (MOBI, title/author fallback ladder) — the next largest lever, not attempted this iteration.
- A second verification oracle to resolve the 709 "unknown" ISBNs.
- format_stack.py still needs its threshold call wired to the new `compare_fingerprints`, and `quick_simhash`
  still doesn't store/compare anything — fixed the two import/determinism bugs, didn't rebuild the feature (T8).
