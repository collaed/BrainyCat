# Response to PR #2 Review + Owner Decisions (2026-09-30)

> Response to [`2026-09-30-pr2-roadmap-review.md`](./2026-09-30-pr2-roadmap-review.md). The review was
> accepted almost in full — it verified every claim against `main` and the live fides instance and
> found real errors in the original plans. This doc records the disposition of each point and the
> owner's decisions on the open questions. Concrete code for every resolved choice is in
> [`../roadmap/decisions-and-code.md`](../roadmap/decisions-and-code.md).

## Disposition summary

| Review point | Disposition |
|---|---|
| §1.1 Built on unmerged code (two trees) | **Accepted.** Phase 0 (land & reconcile) added as prerequisite; more urgent now that multi-tenant touches the same schema. |
| §1.2 / §2 ~10 "recovered ideas" already in `main` | **Accepted.** Gap table adopted; backlog re-graded (M2 schema → P0 bug, M4-LoC → done, M5/M6/M7 → small UI). |
| §1.3 / §4.1 Fusion rubric can't flag ISBN-less pairs | **Accepted — hard error.** Rubric renormalized over present signals + weights fitted on labeled pairs. See decisions-and-code §D4. |
| §1.3 / §4.2 Format conflated with edition | **Accepted — hard error.** 5-class model: exact / stack / edition / translation / probable. See §D5. |
| §1.3 / §4.8 One `processing_status` column ≠ 15 pipelines | **Accepted.** `book_pipeline_state` + `jsonb_typeof='object'` CHECK. See §M1. |
| §1.3 / §4.11 A2 gate misses `writeback_metadata` / `contribute_back` | **Accepted — important.** Central `eligible_books(pipeline)` view + enforcing test. See §A2. |
| §1.4 / §4.7 CPU-bound work blocks the event loop | **Accepted.** Prerequisite in Phase 1 (`asyncio.to_thread` / worker). |
| §1.4 / §4.9 No loop heartbeat visibility | **Accepted.** Loop heartbeat in `/health`, P0. See §M10. |
| §3.2 "63K books" is wrong | **Accepted.** Corrected to measured scale (fides 3,899; published 1,528). |
| §3.3 `_minhash` is k-hash, not bottom-k | **Accepted.** Corrected; LSH banding applies directly. |
| §3.4 Defect 1 worse (no cursor) | **Accepted.** D1 gains a cursor. |
| §3.5 M12 is a runtime `ImportError` | **Accepted.** Included in Phase 1. |
| §3.6 onboarding cites unmerged code as present | **Accepted.** Marked "pending merge." |
| §4.3 Review queue needs keep-recommendation/space sort | **Accepted.** Fold in fides `_side_profile/_recommend`. |
| §4.4 Consolidate, don't add an 8th dedup path | **Accepted.** D-tasks name what they retire. |
| §4.5 `book_files.sha256` | **Accepted.** Phase 1. |
| §4.6 Persistent LSH bands in Postgres | **Accepted.** `minhash_bands` table. See §D3. |
| §4.12 Audio summaries have no text | **Accepted.** ID3/M4B + folder rules + STT last resort. UJ-34 updated. |
| §4.14 Offline: disk budgets mandatory; add LibGen/AA MD5 | **Accepted** (see owner decision A). |
| §4.15 Multilingual embeddings under-prioritized | **Accepted.** Priority raised; serves translation dedup. |
| §4.16 AI: extend Intello vs port router | **Owner override — see decision 2.** Owner chose in-app routing; AI0 (consolidate call sites) still adopted; single Postgres ledger preserves budget control. |
| §4.17 / secrets in `.env` not `secrets.md` | **Accepted as the norm.** `.env`/Docker secrets recommended in docs; the owner's `~/all-secrets.md` is a local operational file outside any repo, not repo config. |
| §4.18 selfhosted-post premature/names providers | **Accepted.** Softened to "summaries you own as files," providers removed pending ToS check. |

## Owner decisions (the review's §9 open questions)

1. **Phase 0 first — YES.** Land and reconcile the two unmerged trees before roadmap execution.
2. **AI routing — IN-APP.** Bring the routing/selection/feeding function into BrainyCat ("Intello in
   spirit" lives in-app). AI0 (consolidate call sites behind `ai.complete(intent, …)`) is the
   prerequisite; a **single cost ledger in BrainyCat's Postgres with per-intent budgets** preserves
   the budget control the reviewer worried about losing.
3. **Multi-tenant — TRUSTED GROUP, "MB-ready."** Multi-user for a group the owner controls
   (family/club); **no duplicate book files** (one physical file per unique content via `canonical_id`);
   **metadata compounds across users** (one user's improvements benefit all). Overrides the review's
   "single-owner" assumption — becomes a real phase. No untrusted-signup abuse controls needed yet.
4. **Stored LLM content — YES, store it** for speed, credit consumption, and consistency. Persist
   `generated_with_model` + `generated_at`; **offer to refresh a summary only after ~6 months** (a
   newer model may do materially better).
5. **LibGen / Anna's Archive metadata — YES** as an identification source (file-MD5 → metadata only;
   no content, no files).
6. **Public GHCR images (M11) — NO / deferred** until after the UI redesign and multi-user hardening.
7. **`ol_local` implementation** — reconcile in Phase 0: BnF SPARQL (author's) + `work_key` (fides').
8. **Metadata trust rule (D):** a user's edit is **auto-honored when constructive/corroborated**
   (adds previously-missing data, or agrees with a public data source); an edit that **contradicts
   existing trusted data is queued for admin review**. Wired to the existing `identity_status`
   machinery. See decisions-and-code §MT2.

## What changes in the roadmap docs

- `master-improvement-plan.md` — "Recovered ideas" reframed as the gap table; M1 → `book_pipeline_state`;
  M2 → P0 bug fix with the real table name `reading_log`; M4 → LoC done, explanation-only; M10 → loop
  heartbeat; M12 → + Calibre ImportError + schema audit; sequencing replaced with Phase 0–4.
- `dedup-overhaul.md` — fusion renormalization/fitting; 5-class model; persistent LSH bands;
  `book_files.sha256`; cursor on D1; CPU-off-loop prerequisite; name retired paths; `_minhash`
  correction.
- `library-vision.md` — central `eligible_books` view (incl. `writeback`/`contribute_back`,
  `is_workbook`); audio-summary path; author-surname agreement; disk budgets + LibGen/AA MD5;
  multilingual embeddings priority; multi-tenant `canonical_id` + shared-metadata model; stored LLM
  content + 6-month refresh.
- `ai-in-app.md` — AI0 first; single Postgres ledger + per-intent budgets; local-first, cloud opt-in
  per intent, never full book text to cloud unless enabled; keys in `.env`.
- `decisions-and-code.md` — **new**: extensive code examples for every choice above.
- `backlog.md`, `onboarding.md`, `selfhosted-post.md`, `user-journeys.md` — re-graded / corrected per
  the review.
