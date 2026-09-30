# BrainyCat — Backlog

> Single prioritized backlog. Consolidates the Ideas Parking Lot from `roadmap.md`, the recovered
> ideas from `roadmap/master-improvement-plan.md`, and the task IDs from the three detailed roadmaps
> (`roadmap/master-improvement-plan.md` M1–M12, `roadmap/library-vision.md` A/B/C, and
> `roadmap/dedup-overhaul.md` D1–D8). Updated 2026-09-30.

## Legend

- **P0** — correctness / reliability / prevents-data-quality-loss; do first.
- **P1** — high user-visible value.
- **P2** — valuable, sequenced after P0/P1.
- **P3** — parked; do when relevant or when a dependency lands.
- **Blocked** — needs a product decision (see `master-improvement-plan.md` Open Questions).

## P0 — Correctness & reliability

| ID | Item | Source | Notes |
|----|------|--------|-------|
| M1 | `processing_status` / scan-failed flag | v2-req R2.11.8 | Never retry a failed book forever; surface failures in admin. |
| M4 | Remove/fix dead LoC source (0% hit rate) | honest-status #7 | ~1,851 wasted attempts / 48h. |
| M10 | Intello circuit breaker + `/health` component status + structured errors | v2-req R2.10.8/9/10 | Reliability + clean AI degradation. |
| M12 | Test-coverage audit + fix `calibre_import` collection errors | roadmap Testing Plan; PR #1 review | Two modules currently uncollectable (`_detect_schema`, `detect_calibre_library`). |
| D1 | Dedup: use dead size-ratio + fuzzy skeleton comparison | dedup-overhaul | Smallest precision fix. |
| A2 | Gate ISBN/title/dedup pipelines on `content_type='book'` | library-vision | Prevents summaries being corrupted by ISBN chasing. |

## P1 — High user-visible value

| ID | Item | Source | Notes |
|----|------|--------|-------|
| A1 | Migration 012: `content_type` + `book_summaries` + `'summary'` link type | library-vision | Foundation for summaries. |
| B1–B4 | Owned-summary detect → ingest → auto-link → **summary-first reading** | library-vision | The headline user payoff. |
| M2 | Reading lifecycle: status, logs, streaks, time estimates, continue-reading shelf | v2-req R2.2/R2.3 | Basic UX expectation + enables wrap-ups. |
| D3 | Dedup: LSH banding candidate generation (replace O(n²)) | dedup-overhaul | Makes dedup actually scale to 63K+. |
| D4 | Dedup: multi-signal fused scorer + classifier | dedup-overhaul | Fixes the false-positive problem. |
| D6 | Dedup: review queue UI + sticky resolutions | dedup-overhaul | Human-in-the-loop merge/keep/edition/not-a-dup. |
| M6 | Page-level FTS snippets + "you already own this" | v2-req R2.11.1/3 | Search inside books; catalog cross-reference. |

## P2 — Valuable, sequenced after P0/P1

| ID | Item | Source | Notes |
|----|------|--------|-------|
| A3 | Summary-aware quality score | library-vision | Summaries score sensibly. |
| B5/M3 | Goldmine intelligence page = self-generated summary edition | v2-req R2.7 + library-vision B5 | Unified; needs Intello. |
| B6 | MCP + search summary integration | library-vision | `list_summaries_of`, `link_summary`. |
| C1 | First-class editions/formats/language grouping | library-vision | Uses `book_links('edition')`. |
| C2 | Pluggable offline reference-DB registry (+ DNB; Wikidata off by default) | library-vision R3 | Google Books documented as API-only. |
| D2 | Cover perceptual hashing (`cover_phash`) + backfill | dedup-overhaul | Independent dedup signal. |
| D5 | Edition-vs-duplicate routing + summary content-type gating | dedup-overhaul | Editions get linked, not merged. |
| D7 | Dedup coverage-guarantee scheduler + audit metric | dedup-overhaul | Backfill before dedup. |
| M4 | Enrichment explanation per book | v2-req R2.11.5 | Transparency. |
| M7 | Bulk metadata editor + cover normalization + resize on ingest | Ideas Parking Lot | Operational hygiene. |
| M9 | Book DNA & wrap-up cards | v2-req R2.4 | Depends on M2. |
| C4 | True semantic embeddings upgrade (replace TF-IDF hash) | library-vision C4 | pgvector columns already exist. |
| C5 | Complete 7-category recommendation dispatch | library-vision C5 | Categories currently return one list. |
| M11 | GHCR images + Prometheus metrics | v2-req R2.11.14/15 | Adoption + observability. |

## P3 — Parked (do when relevant / dependency lands)

| ID | Item | Source | Notes |
|----|------|--------|-------|
| M5 | WordDumb Word Wise + X-Ray; cross-book knowledge graph | v2-req R2.11.7 | Needs Intello. |
| M6-s | Readwise export | Ideas Parking Lot | "Most requested sync." |
| — | Suffix-array / substring dedup | roadmap v3.0 | Stretch after D4. |
| — | KOReader kosync queue RFE | `docs/koreader-rfe-kosync-queue.md` | Written-up request; keep tracked. |
| — | Recipe / citation / RPG-sourcebook extraction | v2-req R2.11.9/10/12 | Niche. |
| — | Comics/manga dedicated reader modes (webtoon, dual-page) | roadmap v1.1 #17/#20 | Partial (comicinfo.py). |
| — | Federation (ActivityPub), book clubs, activity feed | roadmap v2.1 | Social layer. |
| — | Prowlarr integration | v2-req R2.8 | *arr community. |
| — | PDF reflow (fixed-layout → reflowable) | roadmap v3.0 | High effort. |
| — | MARC Z39.50 client | roadmap v3.0 | Library-catalog querying. |
| — | Spaced-repetition flashcards / comprehension quizzes | roadmap v3.0 | Study tools. |
| — | Cross-project MCP / SSO / unified backup | v2-req R2.11.22/23/24 | Ecosystem not ready. |
| — | E-ink optimized mode; offline PWA; Kindle-friendly UI | Ideas Parking Lot | Reader ergonomics. |

## Blocked — needs a product decision

| ID | Item | Decision needed |
|----|------|-----------------|
| M8 | Multi-user isolation + cross-user file dedup (`canonical_id`) | Is BrainyCat single-owner (family/personal) or multi-tenant? Reshapes the data model. |
| M3/M5 | Depth of stored vs on-demand LLM intelligence | Storage + regeneration policy (disk / Intello load). |
| M11 | Public GHCR images now vs after UI redesign | Publish timing. |
