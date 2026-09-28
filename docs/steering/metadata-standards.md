# Metadata Standards (normative)

Applies to all code that identifies books or writes descriptive metadata.
Requirement IDs (`R#`) are defined in `docs/specs/book-identification/requirements.md`.

## 1. Entities

- **Work** — the abstract book. **Edition** — a specific published form (ISBN/ASIN). **File** — a stored
  format of an edition (EPUB, PDF, M4B). One library entry may hold several files of one edition.
- Today a `books` row conflates Work and Edition. Do not deepen that: new code treats
  identifiers as attached to the row, and never assumes one ISBN per work.

## 2. Identifiers

- Canonical ISBN is **ISBN-13, digits only**, checksum-valid. ISBN-10 is converted on input.
  Unicode dashes/spaces stripped. A string failing checksum is never stored as an identifier.
- Other identifier types: `asin`, `oclc`, `lccn`, `doi`, `olid`, `gbid`, `viaf` — stored typed,
  never as free text in `isbn`.
- Every identifier records `source` (how we learned it) and `verified` (checksum ok **and**
  corroborated by a second independent source or by an embedded-in-file origin).
- An identifier found *inside the file* (OPF, copyright page) outranks one guessed from a filename or an API.

## 3. Identification ladder (strongest evidence first)

| Rank | Evidence | Confidence class |
|---|---|---|
| 1 | Checksum-valid ISBN/DOI embedded in file metadata or copyright page | `certain` |
| 2 | Checksum-valid identifier in filename | `probable` |
| 3 | Title + author extracted from file content, matched to an authority record | `probable` |
| 4 | Sentence/content-sample lookup | `possible` |
| 5 | LLM suggestion (must be verified by a structured source) | `possible` |

Rules: a candidate is an identifier set plus title/authors plus a class. Only `certain`/`probable`
candidates that pass the relevance guard are auto-applied. `possible` goes to a review queue.
An LLM never *writes* metadata; it proposes a query that a structured source must confirm.

## 4. Source authority (per field, replaces "shortest/longest wins")

Ordering is configured in one table (`SOURCE_AUTHORITY`), highest first. Initial values:

| Field | Order |
|---|---|
| title, authors, publisher, pubdate, language | national libraries (LoC, BnF, DNB, BNE, BL, NDL) → WorldCat/Open Library → Google Books → commercial → social |
| description | publisher/commercial → Google Books → Open Library → social |
| series | Hardcover/StoryGraph/Babelio → Open Library → derived from title |
| cover | highest resolution passing size/aspect check |
| rating | never merged; stored per source, displayed per source |
| subjects/genres | union, normalized to BISAC/Thema; source retained |

Ties within a rank: agree-with-most-sources wins; then most recently fetched. Length is never a criterion.

## 5. Provenance and locking

Each descriptive field has a provenance record: `value, source, source_rank, confidence, fetched_at, locked`.

- A write may replace the current value only if its source rank is **higher**, or the current value is empty.
- `user` is the highest rank. A user edit sets `locked = true`; enrichment must not touch it.
  Unlock is an explicit user action.
- Every applied change appends a `metadata_history` row (old, new, source, reason). Rollback uses it.
- Re-running enrichment on unchanged inputs produces zero changes (idempotent).

## 6. Normalization

| Field | Standard |
|---|---|
| language | ISO 639-3 lowercase (`eng`, `fra`, `deu`); map 639-1/639-2 and names on input |
| title | as published; strip file-format suffixes, release-group and download-site cruft; split `title: subtitle` |
| authors | stored as separate people; `author_sort` = "Last, First"; no "et al."; translators/editors are roles, not authors |
| pubdate | store value + precision (`year`/`month`/`day`); never invent Jan 1 for a year-only date |
| publisher | trimmed, canonical-cased; imprint aliases collapse via an alias table |
| series | `series_name` + `series_index` (real); no series inferred from a single low-confidence pattern |
| tags | free tags kept separate from BISAC/Thema codes |

## 7. One write path

All descriptive-field writes go through `metadata_apply.apply(book_id, candidates, source)`, which
enforces §5, normalizes per §6, records history, and recomputes quality. A test greps the package
for `UPDATE books SET` outside that module (allowlist for non-descriptive columns such as cover_path,
embedding, search_vector) and fails on violations.

## 8. Verification of results

Before a source result is merged it must pass the relevance guard against what we already know:
identifier match (an ISBN lookup returning a different ISBN is discarded) and title/author similarity
above threshold when no identifier is available. A source returning the same payload for different
queries is quarantined for the run (the ESXi-Cookbook failure mode).
