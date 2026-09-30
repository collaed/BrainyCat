# Catalog & Discovery

## Free Catalog Sources (15)

BrainyCat can search and one-click import from:

| Source | Type | Content |
|--------|------|---------|
| Project Gutenberg | REST API | 70K+ public domain ebooks |
| Standard Ebooks | OPDS | 800+ beautifully typeset public domain books |
| LibriVox | REST API | Public domain audiobooks |
| Internet Archive | Search API | Millions of scanned books |
| Feedbooks | OPDS | Public domain + self-published |
| OAPEN | REST API | Open access academic books |
| arXiv | REST API | Scientific preprints (PDF) |
| Semantic Scholar | REST API | Academic papers |
| CORE | REST API | Open access research outputs |
| Unpaywall | REST API | Free full-text links for DOIs |
| DOAB | REST API | Open access book directory |
| Loyal Books | RSS | Public domain audiobooks |
| ManyBooks | Web scraping | Public domain formatted ebooks |
| GitHub | REST API | Technical books/documentation |
| OpenStax | REST API | Open textbooks |

### Import Flow

```
User searches catalog → results displayed → clicks "Import"
  → server downloads file from source URL
  → creates book record with available metadata
  → triggers enrichment pipeline
```

All downloads are server-side (user's browser never fetches the file).

## OPDS Subscriptions

8 pre-configured OPDS feeds (~75,000 free books total):
- Standard Ebooks
- Feedbooks Public Domain
- Project Gutenberg
- ManyBooks
- Internet Archive
- OAPEN
- DOAB
- Loyal Books

Users can add custom OPDS feeds via `/static/catalog.html`.

The OPDS client is in `opds_catalogs.py` — parses Atom/XML feeds, handles pagination, caches results in `catalog_cache` table.

## Taste Engine

7-category "Book DNA" system for recommendations:

| Category | What it measures |
|----------|-----------------|
| DNA | Core genre + topic preferences |
| Author | Preferred writing styles |
| Community | Books popular with similar readers |
| Hidden Gems | Low-popularity books the user liked |
| Series | Series completion patterns |
| Anti | Topics the user avoids |
| NLP Themes | Extracted themes from highlighted passages |

### How It Works

1. `taste.py` builds a profile from reading history + annotations
2. Uses pgvector embeddings to find books similar to high-rated ones
3. Penalizes books similar to abandoned/low-rated ones
4. Results served via `recommendations.py` → `/api/v1/recommendations`

### Current State

Functional but underutilized — needs a critical mass of reading history + ratings to produce good recommendations. With 63K books and presumably few fully-read, the engine is mostly cold.

## Discovery UI

`/static/catalog.html` provides:
- Search across all 15 sources
- OPDS feed browser
- One-click import
- Source filtering
- Preview (title, author, cover, description before importing)

## Public Catalog

`/static/catalog-public.html` — a public-facing view of the library (no auth required) for sharing with friends. Limited to books marked as shareable.

The OPDS feed at `/opds/` also serves this purpose for e-reader apps.
