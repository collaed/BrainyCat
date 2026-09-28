# Requirements — Book Identification & Consistent Metadata

**Status:** DRAFT for approval. No implementation until approved.
**Standards:** `docs/steering/metadata-standards.md` is normative for the rules below.

## 1. Problem (verified in code, 2026-09-21)

- ~25 modules and 22 route handlers issue their own `UPDATE books SET` (title_cleanup 9, metadata 8,
  isbn 7, deep_enrich 6, …). There is no single write path.
- `metadata.enrich_book` merges by "shortest title / longest description / average rating" and only
  writes `description` and `isbn` when empty. Source quality is not considered.
- One `books.isbn` text column; no typed identifiers, no per-field provenance, no lock on user edits.
- `pubdate` is `TIMESTAMPTZ`, so a year-only date becomes Jan 1.
- Several overlapping modules: `metadata`, `aggregator`, `deep_enrich`, `smart_merge`, `writeback`, `intelligence`.
- Measured coverage (README): ISBN 80%, description 61%, pubdate 46%, tags 5%, series 6%.
- `metadata_audit.rollback_field` interpolates a column name into SQL.

## 2. Glossary

- **Candidate** — identifiers + title/authors + confidence class proposed for a book by one method.
- **Source rank** — position of a source in the per-field authority table.
- **Locked field** — a field a user set or pinned; enrichment cannot change it.
- **Golden set** — a versioned fixture corpus of files with known-correct identification.

## 3. Requirements

| ID | Requirement |
|---|---|
| R1 | ISBNs are stored canonical ISBN-13, checksum-valid; invalid strings are rejected, ISBN-10 converted. |
| R2 | Identifiers are typed (`isbn13`, `asin`, `oclc`, `lccn`, `doi`, `olid`, `gbid`, `viaf`) with `source` and `verified`; a book can hold several. |
| R3 | Identification follows the ladder in standards §3; each attempt yields a Candidate with a confidence class. |
| R4 | Only `certain`/`probable` candidates passing the relevance guard are auto-applied; `possible` goes to a review queue. |
| R5 | An LLM output is never written directly; it must be confirmed by a structured source. |
| R6 | Field values are chosen by per-field source authority (standards §4), not by length. Ratings are stored per source, not merged. |
| R7 | Each descriptive field has provenance (value, source, rank, confidence, fetched_at, locked). |
| R8 | A lower-rank source never overwrites a higher-rank value; user edits lock the field; enrichment never changes locked fields. |
| R9 | All descriptive-field writes go through one function that normalizes, enforces R8, and writes history; a test enforces this. |
| R10 | Normalization follows standards §6 (ISO 639-3 language, split subtitle, author sort, dated precision, alias-collapsed publisher). |
| R11 | Enrichment on unchanged inputs makes zero changes (idempotent). |
| R12 | A result whose identifier conflicts with the book's identifier is discarded; a source returning identical payloads for different queries is quarantined for the run. |
| R13 | Every applied change is in `metadata_history`; any field can be rolled back via a parameterized, allowlisted path. |
| R14 | Duplicate/format stacking uses identifiers first (same ISBN-13 → same edition), then fingerprint verification; works of different editions are linked, not merged. |
| R15 | Identification quality is measured on the golden set; the gate values below must hold before this is called done. |
| R16 | Bulk re-identification supports dry-run and reports intended changes per field before applying. |

## 4. Acceptance (targets, to be confirmed — see Open Questions)

Measured on the golden set (≥200 files, mixed formats/languages/qualities, incl. scans, filename-only, no-ISBN):

- Auto-applied identifications: **precision ≥ 99%** (a wrong auto-apply is worse than an unidentified book).
- Identification rate for books with an embedded or filename ISBN: **≥ 98%**.
- Overall auto+queue coverage: **≥ 90%** (rest reported as unidentifiable, not guessed).
- Re-run on unchanged library: **0 field changes**.
- No `UPDATE books SET` on descriptive fields outside the write path (test green).

## 5. Out of scope (this spec)

Multi-user isolation, federation, new metadata sources, UI redesign, splitting Work/Edition into separate
tables (interim: typed identifiers on the existing row; revisit after R15 passes).

## 6. Open questions

1. Is precision ≥ 99% / identification ≥ 98% the right bar, or do you prefer tighter/looser?
2. Source authority table (standards §4) — agree with the initial ordering, especially national libraries over Google Books?
3. Golden set: can you supply/label ~200 real files from your library (it holds the hard cases), or shall I sample and you review?
4. Do existing user-visible edits in the current DB count as "user"-sourced (locked) on migration, or only edits made after? (Cannot be inferred from history if `metadata_history` is incomplete.)
5. Interim vs proper Work/Edition split — accept typed identifiers only for now?
6. Should the review queue live in the existing Ops page (`metadata_audit`) or a new screen?
