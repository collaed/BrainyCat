# UX/IA Advisor Critique

Produced by a subagent acting as a specialized UX/IA consultant, reviewing `function-inventory.md` and
a first-draft IA. Kept verbatim as the source the final `proposal.md` was built from.

## 1. Critique of the draft IA

**Section count: 8 is too many, and the *reason* it's too many is diagnostic.** The draft's 8 sections map almost 1:1 onto the backend's router files (books.py → Library, enrichment.py → Quality & Duplicates, catalog.py → Discover, admin.py → split across Incoming/Automation/Insights/Settings, ai.py → the open question, social.py → the open question, media.py → Read). That's the tell: the IA was built by asking "what does the backend group things into" rather than "what does a person do when they open this app on a Tuesday night." A single-user/family self-hosted app (per `CLAUDE.md`: "fine for family, not for strangers") gets opened mostly to find-a-book-and-read-it; maintenance tasks (dedup, imports, rules, backups) happen weekly or monthly. Giving maintenance tasks equal top-level billing with the daily loop is the core problem, not the raw breadth (385 endpoints is real and doesn't go away).

**Section-by-section:**

1. **Library** — right call as the default anchor. The proposed book-detail tabs (Overview / Files & Formats / Notes & Clippings / History / Sources) correctly consolidate ~90 `books.py` endpoints without overclaiming. Keep.

2. **Read** — this is the clearest generic-dashboard smell in the draft. A persistent top-nav tab implies something browsable lives there, but there is no "Read" landing page — you don't navigate *to* reading, you navigate to a book and then read it. Compare to how Calibre-Web/Plex treat this: "Read"/"Play" is a button on a title, never an independent nav destination. Demote it: it's an action off a Library card, not a section.

3. **Discover** — conflates two different jobs. `catalog.html`'s free-source acquisition (Gutenberg/LibriVox/OAPEN/OpenStax/Standard Ebooks — verified only **5 of the ~18 catalog.py sources are actually wired into catalog.html's JS**, the rest are backend-only) is "bring new books into my library." Reading goals/streaks and "continue reading" are self-referential progress tracking on books you already own. Recommend: Discover keeps only acquisition (free sources + OPDS + "For You" recommendations); reading goals/streaks move to Insights; "continue reading" becomes a Library shelf, not a Discover feature — the app already has a mechanism for this (Magic Shelves, dynamic views with live counts), use it instead of inventing a new home for it.

4. **Quality & Duplicates** — the best cut in the draft, and it's good for the opposite reason "Read" is bad: these 7 pages (`intelligence.html` + `intel-quality/authors/dupes/content-dupes/series.html` + fingerprints + metadata-ops drift/rollback/validate + filename-history) really are one underlying question — "is my library clean and correct" — viewed through different filters, not a forced grouping. Endorse, with one adjustment: filename-history is a per-book rename audit log; it fits more naturally as the book detail's own History tab, with a library-wide "recent renames" view as a secondary link rather than a full peer tab to Duplicates/Quality.

5. **Incoming & Imports** — reasonable pairing conceptually, but it silently proposes building 8 parallel, differently-shaped import UIs at once (Goodreads/Calibre/ABS/Kobo/Kindle-clippings/Zotero/MARC/URL) — exactly the "expose everything because the endpoint exists" trap the inventory itself is warning about. A single Import page with a source picker (not 8 co-equal flows) is more honest about actual usage frequency (most of these run once, at onboarding).

6. **Automation & Rules** — bundles a real user-facing config (consumption rules, currently orphaned in `rules.html`) with pure observability (job status, enrichment log/activity/cooldown, rate-limit status). Those are different audiences even in a single-user app: "configure how auto-tagging behaves" vs. "is the background scheduler stuck." The monitoring half doesn't deserve top-level nav peerage with Library.

7. **Insights** — fine grouping in principle (stats.html + efficiency.html + Wrapped + streak), but it mixes human-facing reading analytics (streaks, Wrapped, reading stats) with `efficiency.html`, which is an enrichment-throughput/system metric, not a personal insight. Split: personal reading insights stay in Insights; enrichment efficiency/source-stats move to Settings > System Status.

8. **Settings** — correctly the catch-all for "set once," but the inventory shows this bucket currently has **zero UI at all**, including backup/restore — which `honest-status.md` marks "✅ Works" as a feature. A documented, working, core safety feature with no UI is a bigger real gap than any of the flashier AI-feature gaps and should be prioritized accordingly, not just slotted in as item 8 of 8.

**Generic-SaaS-dashboard smells to flag explicitly:**
- "Read" as a persistent nav tab (dashboard "Reports" tab instinct, doesn't fit an item you always enter with a specific book id).
- Splitting library-health concerns three ways (Quality & Duplicates / Automation & Rules / Insights) rather than recognizing job logs, rate-limits, and enrichment stats are all the same "system status" concern and belong together under Settings.
- Pre-emptive flag: don't build a Pending/Confirmed/Dismissed kanban board for duplicate review. Duplicate resolution is a sequence of yes/no pair decisions, better served by a simple review list with inline actions than a kanban board with drag targets.

## 2. Answers to the open questions

**Q1 — Is 8 sections right, or too many?** Too many, but the fix is nav *depth*, not deleting functionality. Collapse to ~4 primary content sections + a Settings icon. Everything from Automation & Rules, most of Incoming & Imports, and the observability half of Insights moves under Settings, which is allowed to be deep (opened rarely) in a way the primary content nav should not be.

**Q2 — Should AI features get their own top-level section?** No — book detail modal (and inline reader affordances) only. Every one of the 14 endpoints is inherently book-scoped; a standalone destination would just be an empty book picker. Also, Intello being a documented single point of failure means a permanent nav tab could go visibly empty as a group, which is worse UX than a contextual button that just doesn't render when it's down. Exception: `/story-graphs/compare` is inherently multi-book and belongs in Insights or a Library compare flow.

**Q3 — Should Social be hidden by default?** Yes. `honest-status.md` explicitly marks federated social a stub with cross-instance untested, plus no multi-user data isolation — a Social nav item would imply connections the app can't honestly deliver. But sleep-detection and reading streaks/challenges are personal, non-federated features filed under the social router by accident of backend organization — pull those into Insights; they're safe.

**Q4 — Does the merged tabbed-page pattern respect the vanilla-HTML/no-build-step constraint?** Yes — plain JS show/hide, `?tab=` query param for deep-linking, reuse `api.js`'s `BC` helper, no framework needed. Risk to flag: `honest-status.md`'s own Architecture Decisions table warns vanilla JS "will get painful if UI grows much more," and `reader.html` (1,288 lines) is the cautionary example. Keep each tab's JS in its own file loaded on demand, not concatenated into one file.

## 3. Naming convention

Name by what the feature does for the user, never by backend module/router filename/internal codename. If a family member wouldn't say the word out loud to describe what they're doing, don't put it in the nav.

- Drop "Intel"/"Intelligence" → "Quality & Duplicates".
- Drop "Ops" → "Metadata Changes".
- Drop "Efficiency" as a personal label → "Enrichment Activity", in Settings > System Status.
- "Rules" is ambiguous alone → "Auto-tag Rules" / "Automation".
- "Filename History" → "Renames", surfaced primarily per-book.
- "Wrapped" is acceptable branding if wanted; plain alternative is "Year in Review".
- "Incoming," "Catalog," "Stats," "For You" are already fine.
- Fix the existing inconsistency: `index.html` and `stats.html` each hand-roll a *different* nav with different items in a different order today. Ship one shared `nav.js` array included by every page, same pattern `api.js` already establishes.
- Mechanical rules: Title Case; one or two words per label; no internal abbreviations needing decoding; icon+emoji always paired with text, never icon-only.

## 4. Concrete nav + tab breakdowns

Top-level: **Library** (default) · **Discover** · **Fix Library** · **Insights** · **Settings** (gear icon).
Reading/listening is not a nav item — an action on a book card.

**Library book detail tabs:** Overview · Files & Formats · Notes & Clippings · History (metadata changes + this book's renames) · Sources (which of 32 enrichment sources contributed which field — no UI today).

**Fix Library tabs:** Duplicates (ISBN + content-fingerprint, filter chips not separate pages) · Quality · Series · Authors · Metadata Changes. `intelligence.html`'s current overview/enrichment-stats becomes this page's landing summary, not its own tab.

**Settings sections:** Account · API & Sync (the one key KOReader/Kobo/WebDAV/MCP all use) · Appearance · **Backup & Restore** (currently zero UI — highest-priority build item in this whole redesign) · Automation Rules (surfaces orphaned rules.html) · Import Library Data (one page, source picker, replacing 8 co-equal import flows) · System Status (job status, enrichment activity/log/source-stats/cooldown, rate-limits).

## 5. Deliberately not building UI for yet

- Federated social/clubs — stub, cross-instance untested, no multi-user isolation.
- Kobo sync (20%, no kepub/bookmark sync) and WebDAV (30%, read-only) — device-facing; label honestly if ever surfaced.
- Experimental features (mind-map, share-card, heatmap, PDF-embed, evaluate/*) — off by default via env var; at most a Labs toggle gated on the var actually being set.
- Browse-by-genre/BISAC/series as a primary nav surface — coverage 4-6%, would look broken for nearly every book today.
- Kindle delivery as a primary one-click action — untested end-to-end; keep secondary.
- MCP server (28 tools) — protocol/agent-facing only; one mention in Settings > API & Sync, never a standalone page.
- Story Graph *generation* (creative-writing tool, distinct from real book-scoped story-arc analysis) — flagged back to product scope, not just placement.
- Custom feeds/RSS, podcast feeds — protocol-facing; surface only as a "copy feed URL" action, not a page.
