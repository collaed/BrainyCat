# Function Inventory — what BrainyCat can do vs. what the UI exposes

Generated 2026-09-26 by grepping `brainycat/routes/*.py` + `web.py` for route decorators (385 total
endpoints) and every `static/*.html` page for the endpoints it actually calls (67 distinct patterns
called, across all pages combined). **~82% of the API surface has no UI path to it at all.**

11 of 25 static pages have zero inbound links from any other page: `app.html`, `catalog-public.html`,
`efficiency.html`, `index.old.html`, `intel-authors.html`, `intel-content-dupes.html`, `intel-dupes.html`,
`intel-quality.html`, `intel-series.html`, `rules.html` (`setup.html` is fine — reached by server redirect).

Legend: **UI** = a page calls this today. **orphan** = a page calls it but the page itself isn't linked
from anywhere. **none** = no page calls it at all.

## 1. Library core (books.py, routes/books.py — ~90 endpoints)
- Upload, list, get, update, delete, cover, file serving — **UI** (index.html, catalog.html)
- Bulk tag/enrich/delete, batch operations — **none**
- Format conversion (EPUB↔PDF↔MOBI↔KEPUB), TTS, STT, audio restore/diagnose/merge-chapters — **none**
- Send to Kindle / send to device — **UI** (index.old.html only — the *retired* page)
- ISBN/identifier extraction, cover download/generate/refresh, classify, writeback — **none**
- EPUB tools: check, lint, split, word-wise, x-ray, footnotes, hyphenate, chapter detection — **none**
- Notes, clippings, bilingual view, readability, summary, goldmine (highlights export) — partial (bilingual.html **orphan**)
- Series (list/reorder/merge), works, editions, isbn-region, compare, timeline — series.html **orphan**
- OCR, OCR-to-EPUB, PDF-to-EPUB, page extraction, PDF page image — **none**
- Full-text search, content indexing — **none**
- Reviews, sources (which enrichment sources contributed what) — **none**

## 2. Metadata identification & enrichment (enrichment.py — ~40 endpoints)
- Intelligence: quality, series-gaps, duplicates (content + exact + author), enrichment-stats, efficiency —
  **intelligence.html** links to sub-pages **intel-quality/authors/dupes/content-dupes/series.html**, all
  **orphaned** (only reachable if you already know the URL)
- Fingerprint compute/find-duplicates/matches — **none**
- ISBN lookup/intelligence/links, extract — **metadata-ops.html** partial, mostly **none**
- Embeddings generate/reindex — **none**
- Per-source enrichment views (Open Library enhanced, VIAF, Inventaire, BookBrainz, ISFDB, StoryGraph,
  Hardcover, regional) — **none**
- Deep-enrich, batch classify, fix-titles, resolve-work-ids — **none**
- Enrichment log/activity/source-stats/cooldown — **none**

## 3. Catalog discovery — free sources (catalog.py — ~35 endpoints)
- Gutenberg, LibriVox, Standard Ebooks, GitHub, OAPEN, OpenStax, open textbooks, ManyBooks,
  free-computer-books, Feedbooks, Internet Archive, DOAB, Loyal Books, arXiv, Semantic Scholar, CORE,
  Unpaywall, Packt, web-search — **catalog.html** covers a search UI but likely only a few of these 18
  sources are wired to it (needs verification against catalog.html's JS)
- OPDS subscriptions/browse/import, cross-link, check-owned — **none**
- Sync gutenberg/librivox/crosslinks — **none**

## 4. Admin & operations (admin.py — ~90 endpoints, the biggest single file)
- Stats overview/dashboard/rate-limits/scraper-diagnostics/isbn-regions — **stats.html** covers overview only
- Backup/restore, disk usage — **none** (no UI at all for backups — a documented core feature!)
- Imports: Goodreads, Audiobookshelf, Calibre (+ calibre-library), Kobo, Kindle clippings, Zotero, MARC,
  URL — **none** (all import paths are curl-only today)
- Jobs (background job status), plugins, custom columns, virtual libraries — **none**
- Consumption rules (filename pattern → auto-tag) — **rules.html**, **orphaned**
- Experimental features (mind-map, share-card, heatmap, PDF-embed, evaluate) — **none**
- Format-duplicates stack/auto-stack, merge candidates/merge — **none**
- Metadata ops (history, drift, rollback, validate, flag, bugs) — **metadata-ops.html**, **orphaned**
- Filename history (rename audit + revert) — **filename-history.html**, **orphaned**
- Recommendations (similar/for-you/external), Wrapped (year-in-review), export (Obsidian/MARC) — **none**
- Notify, notes export — **none**

## 5. AI features (ai.py — 14 endpoints, needs Intello)
- Recap, ask-the-book, auto-tag, explain, translate, summarize-chapters, similar-passage search,
  story-graph (+ compare + SVG) — **none** (no page calls any of these; `ai_router` is entirely unreached)

## 6. Reading & sync (reader.py — ~55 endpoints, the app's second-biggest file)
- Progress, bookmarks, annotations (+ sharing), pen annotations — **reader.html**
- Incoming (list/status/scan/confirm/reject) — **incoming.html**
- Recommendations (profile/category/from-library), taste-profile — **recommendations.html**, **orphaned**
- OPDS catalog/search/recommendations, OPDS-PS manifest/page — **none** (external readers only)
- Reading goals, streak, log, stats, speed-test — **none**
- Shelves, collections (+ books in collection) — **none**
- Lending (request/approve/deny/loans), challenges — **none**
- Highlights export, annotated-download, notebook — **none**
- Book status (want-to-read/reading/read) — **none**

## 7. Social (social.py — 27 endpoints)
- Federated profiles/follow/refresh, activity feed, clubs (create/join/discuss) — **none**
- Sleep detection report/rewind — **none**
- Streaks, challenges, quotes, custom feeds (RSS) — **none**

## 8. Media/audio (media.py — 13 endpoints)
- TTS voices, translation backends, converters list — **none**
- EPUB merge/batch-check, EPUB styles — **none**
- Podcast feeds (per-book, learning, summaries) — **none**
- Audio-products (summary/reinforcement) — **none**
- Audio player itself — **player.html**, linked from **reader.html** only (3 inbound links total)

## 9. Auth & settings (auth.py + routes/auth.py — ~15 endpoints)
- Login/logout/me/users, API keys (create/list/revoke), preferences, theme — **login.html** for login;
  no page for API key management, theme switching, or the settings shown in `routes/auth.py` (Packt
  credentials, catalog languages) — **none**

## 10. Protocol compat (kobo.py, kosync.py, webdav.py, abs_compat.py) — device-facing, no UI needed
These are consumed by e-reader devices/apps directly (Kobo, KOReader, WebDAV clients, Audiobookshelf
app) — correctly have no browser UI, not a gap.

## Headline numbers
- **385** total backend endpoints.
- **67** distinct endpoint patterns actually called by any page.
- **25** static pages exist; **11** are unreachable by navigation (orphaned).
- Entire routers with **zero** UI: `ai.py` (14 endpoints), most of `social.py`, most of `media.py`,
  most of `catalog.py`'s 18 free sources, and the majority of `admin.py`'s 90.
