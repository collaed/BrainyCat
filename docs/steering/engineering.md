# Engineering Steering

Distilled from the working conventions of a sibling project (DivingClub-Manager),
adapted to BrainyCat. Applies to every change.

## Code philosophy

- Minimal code. No speculative features, config or abstractions for single-use code.
- Fix the root cause, not the symptom. The `relevance_guard` exists because of a symptom
  fix-after-incident (108 books renamed); the cause was accepting unverified results.
- Reuse an existing module before writing a new one. This repo already has overlapping
  modules (`metadata`, `aggregator`, `deep_enrich`, `smart_merge`, `writeback`,
  `intelligence`); consolidate, don't add a seventh.
- Surgical diffs: every changed line traces to the request. Flag dead code, don't delete it in passing.
- Don't change dependencies without approval.
- Read config through `brainycat.config.settings`, not `os.environ` scattered in modules.

## Spec-first for non-trivial features

1. `requirements.md` — glossary, numbered normative rules (`R1…`), acceptance criteria, open questions.
2. `tasks.md` — dependency-ordered; each task cites the requirements it satisfies and states its verification.
3. **No implementation until the plan is approved.** Requirements not yet true in code are written
   as targets and the gap is listed under open questions.

## Data safety (the lesson of every enrichment bug so far)

- Anything that rewrites existing rows says so in the commit/changelog, what it touches, and how to check it.
- Back up (`POST /api/v1/backup`) before running a migration or bulk re-enrichment on a real library.
- Bulk jobs are dry-run-able and log what they *would* change before changing it.
- External sync/enrichment must not clobber local edits (see metadata-standards §Provenance).
- Health-gate deploys: hit `/health` after restart; roll back if it isn't green.

## Scheduled work

Every scheduler loop records a heartbeat only on real success. A blanket "after" hook
fires even when the job caught and swallowed its exception. Jobs return a bool/outcome
and the heartbeat is gated on it. No bare `except: pass` without a log line.

## Testing

- New identification/merge/normalization logic ships with unit tests in the same change
  (pure functions first: no DB, no network — mock sources).
- Regression tests reproduce the bug before the fix.
- Golden-set tests (see spec) are the acceptance gate for identification quality.

## Don't

- Don't add sources or features that bypass the metadata write path.
- Don't hard-code personal identifiers, hosts or credentials in code, docs or defaults.
- Don't trust request headers/cookies for identity without verification.
- Don't create ad-hoc verification scripts when a test covers it.
- Don't add documentation files beyond the spec/steering set unless asked.
