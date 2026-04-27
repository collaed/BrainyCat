"""Routes: enrichment."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query

from brainycat import db, intelligence
from brainycat.auth import get_current_user, require_admin
from brainycat.http_client import get_client

if TYPE_CHECKING:
    from brainycat.routes.models import BatchActionsBody, CreateSeriesBody, LinkDuplicateBody, MergeAuthorsBody

router = APIRouter(prefix="/api/v1", tags=["enrichment"])


@router.get("/intelligence/quality")
async def intel_quality(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.quality_report()


@router.get("/intelligence/series-gaps")
async def intel_gaps(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.series_suggestions()


@router.get("/intelligence/duplicates")
async def intel_dupes(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.find_duplicates()


@router.get("/intelligence/author-suggestions")
async def intel_authors(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await intelligence.author_suggestions()


@router.post("/intelligence/apply-series")
async def intel_apply_series(body: CreateSeriesBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_create_series(body.series_name, body.book_ids)


@router.post("/intelligence/merge-authors")
async def intel_merge(body: MergeAuthorsBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_merge_authors(body.keep_id, body.merge_id)


@router.post("/intelligence/link-duplicate")
async def intel_link_dup(body: LinkDuplicateBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_link_duplicate(body.book_a_id, body.book_b_id, body.link_type)


@router.post("/intelligence/batch")
async def intel_batch(body: BatchActionsBody, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await intelligence.apply_batch(body.actions)


# ── Progress, bookmarks, annotations ─────────────────────────────────────


@router.get("/intelligence/content-duplicates")
async def content_dupes(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.duplicates import find_content_duplicates

    return await find_content_duplicates()


# ── Batch PDF cover extraction ───────────────────────────────────────────


@router.post("/fingerprints/compute")
async def compute_fps(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.fingerprints import compute_all_fingerprints

    return await compute_all_fingerprints(batch_size=50)


@router.post("/fingerprints/find-duplicates")
async def find_fp_dupes(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.fingerprints import find_duplicates_by_content

    return await find_duplicates_by_content(batch_size=100)


@router.get("/fingerprints/matches")
async def get_fp_matches(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.fingerprints import get_duplicate_matches

    return await get_duplicate_matches()


@router.post("/fingerprints/matches/{match_id}/{action}")
async def resolve_fp_match(match_id: str, action: str, _u: Any = Depends(get_current_user)) -> dict[str, bool]:
    from brainycat.fingerprints import resolve_match

    return await resolve_match(match_id, action)


@router.get("/fingerprints/status")
async def fp_status(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    total = await db.fetch_one("SELECT count(*) as n FROM book_fingerprints")
    pending_fp = await db.fetch_one("""
        SELECT count(*) as n FROM books b JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
    """)
    pending_matches = await db.fetch_one("SELECT count(*) as n FROM duplicate_matches WHERE status = 'pending'")
    return {
        "fingerprinted": total["n"] if total else 0,
        "pending_fingerprint": pending_fp["n"] if pending_fp else 0,
        "pending_matches": pending_matches["n"] if pending_matches else 0,
    }


# ── LibriVox import ──────────────────────────────────────────────────────


# ── Genre classification ─────────────────────────────────────────────────


@router.post("/isbn/extract")
async def extract_isbns(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.isbn import batch_extract_isbns

    return await batch_extract_isbns(limit=100)


@router.get("/intelligence/enrichment-stats")
async def enrichment_stats(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Enrichment activity by method over time periods."""
    rows = await db.fetch_all("""
        SELECT method,
            count(*) FILTER (WHERE success AND created_at > now() - interval '1 hour') as success_1h,
            count(*) FILTER (WHERE NOT success AND created_at > now() - interval '1 hour') as fail_1h,
            count(*) FILTER (WHERE success AND created_at > now() - interval '24 hours') as success_24h,
            count(*) FILTER (WHERE NOT success AND created_at > now() - interval '24 hours') as fail_24h,
            count(*) FILTER (WHERE success AND created_at > now() - interval '7 days') as success_7d,
            count(*) FILTER (WHERE success AND created_at > now() - interval '30 days') as success_30d
        FROM enrichment_log
        GROUP BY method ORDER BY method
    """)
    return {
        "methods": [
            {
                "method": r["method"],
                "1h": {"success": r["success_1h"], "fail": r["fail_1h"]},
                "24h": {"success": r["success_24h"], "fail": r["fail_24h"]},
                "7d": r["success_7d"],
                "30d": r["success_30d"],
            }
            for r in rows
        ],
        "totals": {
            "with_isbn": (await db.fetch_one("SELECT count(*) as n FROM books WHERE isbn IS NOT NULL AND isbn != ''"))["n"],
            "enriched": (await db.fetch_one("SELECT count(*) as n FROM books WHERE quality_score > 0"))["n"],
            "total": (await db.fetch_one("SELECT count(*) as n FROM books"))["n"],
            "in_series": (await db.fetch_one("SELECT count(DISTINCT book_id) as n FROM books_series"))["n"],
            "series_count": (await db.fetch_one("SELECT count(*) as n FROM series"))["n"],
            "fingerprinted": (await db.fetch_one("SELECT count(*) as n FROM book_fingerprints"))["n"],
        },
    }


# ── Workbook flag ────────────────────────────────────────────────────────


@router.get("/intelligence/efficiency")
async def efficiency_dashboard(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Comprehensive efficiency metrics for all algorithms."""
    # ISBN pipeline
    isbn_stats = await db.fetch_one("""
        SELECT
            count(*) FILTER (WHERE isbn IS NOT NULL AND isbn != '') as with_isbn,
            count(*) FILTER (WHERE isbn IS NULL OR isbn = '') as without_isbn,
            count(*) FILTER (WHERE quality_score >= 75) as high_quality,
            count(*) FILTER (WHERE quality_score BETWEEN 50 AND 74) as medium_quality,
            count(*) FILTER (WHERE quality_score BETWEEN 1 AND 49) as low_quality,
            count(*) FILTER (WHERE quality_score = 0) as not_enriched,
            count(*) as total
        FROM books
    """)

    # ISBN → enrichment success rate
    isbn_to_enrich = await db.fetch_one("""
        SELECT
            count(DISTINCT el.book_id) FILTER (WHERE el.success AND b.isbn IS NOT NULL) as isbn_led_to_data,
            count(DISTINCT el.book_id) FILTER (WHERE NOT el.success AND b.isbn IS NOT NULL) as isbn_no_data,
            count(DISTINCT el.book_id) FILTER (WHERE el.success AND b.isbn IS NULL) as no_isbn_got_data,
            count(DISTINCT el.book_id) FILTER (WHERE NOT el.success AND b.isbn IS NULL) as no_isbn_no_data
        FROM enrichment_log el
        JOIN books b ON b.id = el.book_id
    """)

    # Per-source hit rates
    source_stats = await db.fetch_all("""
        SELECT method,
            count(*) FILTER (WHERE success) as hits,
            count(*) FILTER (WHERE NOT success) as misses,
            count(*) as total,
            CASE WHEN count(*) > 0 THEN round(100.0 * count(*) FILTER (WHERE success) / count(*), 1) ELSE 0 END as hit_rate
        FROM enrichment_log
        WHERE method NOT IN ('writeback', 'isbn_extract', 'series_detect')
        GROUP BY method ORDER BY hit_rate DESC
    """)

    # Fingerprint progress
    fp_stats = await db.fetch_one("""
        SELECT
            (SELECT count(*) FROM book_fingerprints) as fingerprinted,
            (SELECT count(*) FROM duplicate_matches WHERE status = 'pending') as pending_dupes,
            (SELECT count(*) FROM duplicate_matches WHERE status = 'confirmed') as confirmed_dupes,
            (SELECT count(*) FROM duplicate_matches WHERE status = 'dismissed') as dismissed_dupes
    """)

    # Series
    series_stats = await db.fetch_one("""
        SELECT
            (SELECT count(*) FROM series) as series_count,
            (SELECT count(DISTINCT book_id) FROM books_series) as books_in_series
    """)

    # Writeback
    wb_stats = await db.fetch_one("""
        SELECT count(*) FILTER (WHERE success) as written_back
        FROM enrichment_log WHERE method = 'writeback'
    """)

    # Cover stats
    cover_stats = await db.fetch_one("""
        SELECT
            count(*) FILTER (WHERE cover_path IS NOT NULL) as with_cover,
            count(*) FILTER (WHERE cover_path IS NULL) as without_cover
        FROM books
    """)

    return {
        "isbn": dict(isbn_stats) if isbn_stats else {},
        "isbn_effectiveness": dict(isbn_to_enrich) if isbn_to_enrich else {},
        "sources": [dict(r) for r in source_stats],
        "fingerprints": dict(fp_stats) if fp_stats else {},
        "series": dict(series_stats) if series_stats else {},
        "writeback": {"written_back": wb_stats["written_back"] if wb_stats else 0},
        "covers": dict(cover_stats) if cover_stats else {},
    }


# ── Bilingual content ────────────────────────────────────────────────────


@router.post("/embeddings/generate")
async def gen_embeddings(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.embeddings import embed_all_books

    return await embed_all_books(limit=100)


@router.post("/embeddings/reindex")
async def reindex_embeddings(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.embeddings import reindex_all

    return await reindex_all()


# ── UI Skin selection ────────────────────────────────────────────────────


@router.get("/sources/coverage")
async def source_coverage(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.aggregator import library_source_coverage

    return await library_source_coverage()


# ── Calibre import ───────────────────────────────────────────────────────


@router.get("/enrichment/open-library-enhanced")
async def ol_enhanced(title: str = Query(""), isbn: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.open_library_enhanced import search_enhanced

    return await search_enhanced(title=title or None, isbn=isbn or None) or {}


@router.get("/enrichment/viaf")
async def viaf_search(name: str = Query(""), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.authority import search_viaf

    return await search_viaf(name)


@router.get("/enrichment/inventaire")
async def inventaire_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.authority import search_inventaire

    return await search_inventaire(q)


@router.get("/enrichment/bookbrainz")
async def bookbrainz_search(q: str = Query(""), _u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.sources.authority import search_bookbrainz

    return await search_bookbrainz(q)


@router.get("/enrichment/sources")
async def enrichment_sources(_u: Any = Depends(get_current_user)) -> list[dict[str, str]]:
    """List all available enrichment sources."""
    return [
        {"id": "google_books", "name": "Google Books", "type": "metadata", "auth": "none"},
        {"id": "open_library", "name": "Open Library (basic)", "type": "metadata", "auth": "none"},
        {"id": "open_library_enhanced", "name": "Open Library (Works + Ratings)", "type": "metadata+ratings", "auth": "none"},
        {"id": "gutendex", "name": "Gutendex (Gutenberg)", "type": "metadata", "auth": "none"},
        {"id": "loc", "name": "Library of Congress", "type": "metadata", "auth": "none"},
        {"id": "amazon", "name": "Amazon (via Google proxy)", "type": "metadata+covers", "auth": "none"},
        {"id": "viaf", "name": "VIAF (author authority)", "type": "author_disambiguation", "auth": "none"},
        {"id": "isni", "name": "ISNI (author IDs)", "type": "author_disambiguation", "auth": "none"},
        {"id": "inventaire", "name": "Inventaire (Wikidata-backed)", "type": "metadata", "auth": "none"},
        {"id": "bookbrainz", "name": "BookBrainz", "type": "metadata+identifiers", "auth": "none"},
        {"id": "edelweiss", "name": "Edelweiss (publisher catalog)", "type": "metadata+covers", "auth": "none"},
        {"id": "google_images", "name": "Google Images (covers)", "type": "covers", "auth": "none"},
        {"id": "apple_books", "name": "Apple Books (covers)", "type": "covers", "auth": "none"},
        {"id": "bookcover_api", "name": "Bookcover API (aggregator)", "type": "covers", "auth": "none"},
    ]


# ── Calibre plugin sync endpoints ─────────────────────────────────────────


@router.get("/library/health")
async def library_health(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Comprehensive library health report."""
    total = await db.fetch_one("SELECT count(*) as n FROM books")
    n = total["n"] if total else 0
    no_cover = await db.fetch_one("SELECT count(*) as n FROM books WHERE cover_path IS NULL")
    no_isbn = await db.fetch_one("SELECT count(*) as n FROM books WHERE isbn IS NULL")
    no_desc = await db.fetch_one("SELECT count(*) as n FROM books WHERE description IS NULL OR description = ''")
    no_author = await db.fetch_one(
        "SELECT count(*) as n FROM books b WHERE NOT EXISTS (SELECT 1 FROM books_authors ba WHERE ba.book_id = b.id)"
    )
    dup_authors = await db.fetch_all("""
        SELECT lower(regexp_replace(name, '[^a-zA-Z ]', '', 'g')) as norm, array_agg(name) as names, count(*) as cnt
        FROM authors GROUP BY norm HAVING count(*) > 1 ORDER BY cnt DESC LIMIT 20
    """)
    series_gaps = await db.fetch_all("""
        SELECT s.name, array_agg(b.series_index ORDER BY b.series_index) as indices
        FROM books_series bs JOIN series s ON s.id = bs.series_id JOIN books b ON b.id = bs.book_id
        GROUP BY s.name HAVING count(*) > 1
    """)
    gaps = []
    for sg in series_gaps:
        indices = sorted([i for i in (sg["indices"] or []) if i])
        if indices and indices[-1] > len(indices):
            gaps.append({"series": sg["name"], "have": indices, "missing": [i for i in range(1, int(indices[-1]) + 1) if i not in indices]})

    return {
        "total_books": n,
        "missing_covers": {"count": no_cover["n"], "pct": round(no_cover["n"] / max(n, 1) * 100, 1)},
        "missing_isbn": {"count": no_isbn["n"], "pct": round(no_isbn["n"] / max(n, 1) * 100, 1)},
        "missing_description": {"count": no_desc["n"], "pct": round(no_desc["n"] / max(n, 1) * 100, 1)},
        "missing_author": {"count": no_author["n"], "pct": round(no_author["n"] / max(n, 1) * 100, 1)},
        "duplicate_authors": [{"names": d["names"], "count": d["cnt"]} for d in dup_authors],
        "series_gaps": gaps[:10],
    }


# ── "What should I read next" from own library ───────────────────────────


@router.get("/intelligence/exact-duplicates")
async def exact_duplicates(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    from brainycat.fingerprints import find_exact_duplicates

    return await find_exact_duplicates()


# ── Ingest pipeline ───────────────────────────────────────────────────────


@router.get("/enrichment/storygraph")
async def storygraph_search(title: str = Query(""), author: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.social_reads import search_storygraph

    return await search_storygraph(title, author) or {}


@router.get("/enrichment/hardcover")
async def hardcover_search(title: str = Query(""), author: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.sources.social_reads import search_hardcover

    return await search_hardcover(title, author) or {}


@router.post("/intelligence/fix-titles")
async def fix_titles(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    from brainycat.title_cleanup import run_title_cleanup_cycle

    return await run_title_cleanup_cycle()


# ── Gotify notifications ──────────────────────────────────────────────────


@router.post("/intelligence/classify-batch")
async def classify_batch(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Classify untagged books that have ISBNs — fetch genres from Google Books."""
    rows = await db.fetch_all("""
        SELECT b.id, b.isbn, b.title FROM books b
        WHERE b.isbn IS NOT NULL AND length(b.isbn) >= 10
          AND NOT EXISTS (SELECT 1 FROM books_tags bt WHERE bt.book_id = b.id)
        LIMIT 20
    """)
    classified = 0
    for r in rows:
        try:
            from brainycat.rate_limit import rate_limiter

            await rate_limiter.wait("google")
            c = get_client()
            resp = await c.get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{r['isbn']}&maxResults=1")
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    cats = items[0].get("volumeInfo", {}).get("categories", [])
                    for cat in cats[:5]:
                        cat = cat.strip()
                        if len(cat) < 2:
                            continue
                        await db.execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", cat)
                        tag = await db.fetch_one("SELECT id FROM tags WHERE name = $1", cat)
                        if tag:
                            await db.execute(
                                "INSERT INTO books_tags (book_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", r["id"], tag["id"]
                            )
                    if cats:
                        classified += 1
        except Exception:
            pass
    return {"classified": classified, "checked": len(rows)}


# ── KOReader Sync ─────────────────────────────────────────────────────────


@router.get("/enrichment/isfdb")
async def isfdb_search(title: str = Query(""), _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Search ISFDB for sci-fi/fantasy series, awards, publication history."""
    import re

    c = get_client()
    try:
        resp = await c.get(f"https://isfdb.org/cgi-bin/se.cgi?arg={title}&type=All+Titles", headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {"results": []}
        results = []
        for m in re.finditer(r'<a href="(https://isfdb\.org/cgi-bin/title\.cgi\?\d+)">([^<]+)</a>', resp.text):
            results.append({"url": m.group(1), "title": m.group(2).strip()})
            if len(results) >= 10:
                break
        # Get details for first result
        if results:
            detail_resp = await c.get(results[0]["url"], headers={"User-Agent": "Mozilla/5.0"})
            if detail_resp.status_code == 200:
                series_m = re.search(r'<a href="[^"]*series\.cgi[^"]*">([^<]+)</a>', detail_resp.text)
                award_matches = re.findall(r'<a href="[^"]*award_details[^"]*">([^<]+)</a>', detail_resp.text)
                year_m = re.search(r"Date:\s*</td>\s*<td[^>]*>(\d{4})", detail_resp.text)
                results[0]["series"] = series_m.group(1) if series_m else None
                results[0]["awards"] = award_matches[:5]
                results[0]["year"] = year_m.group(1) if year_m else None
        return {"results": results}
    except Exception:
        return {"results": []}


# ── Zotero Import ─────────────────────────────────────────────────────────


@router.get("/enrichment/regional/{source}")
async def regional_search(
    source: str, title: str = Query(""), isbn: str = Query(""), author: str = Query(""), _u: Any = Depends(get_current_user)
) -> dict[str, Any]:
    """Search a regional metadata source. Sources: babelio, dnb, fantastic_fiction, thalia, bol_nl, skoob, casa_del_libro, rakuten, douban, myanimelist, comicvine, worldcat."""
    from brainycat.sources import regional

    fn_map = {
        "babelio": regional.search_babelio,
        "dnb": regional.search_dnb,
        "fantastic_fiction": regional.search_fantastic_fiction,
        "thalia": regional.search_thalia,
        "bol_nl": regional.search_bol_nl,
        "skoob": regional.search_skoob,
        "casa_del_libro": regional.search_casa_del_libro,
        "rakuten": regional.search_rakuten,
        "douban": regional.search_douban,
        "myanimelist": regional.search_myanimelist,
        "comicvine": regional.search_comicvine,
        "worldcat": regional.search_worldcat,
        "bnf": regional.search_bnf,
        "british_library": regional.search_british_library,
        "bne": regional.search_bne,
        "ndl": regional.search_ndl,
    }
    fn = fn_map.get(source)
    if not fn:
        return {"error": f"unknown source: {source}", "available": list(fn_map.keys())}
    import inspect

    sig = inspect.signature(fn)
    kwargs = {}
    for p in sig.parameters:
        if p == "title":
            kwargs["title"] = title
        elif p == "isbn":
            kwargs["isbn"] = isbn
        elif p == "author":
            kwargs["author"] = author
    return await fn(**kwargs) or {"result": None}


# ── Comprehensive stats dashboard ─────────────────────────────────────────


@router.post("/intelligence/resolve-work-ids")
async def resolve_work_ids(_a: Any = Depends(require_admin)) -> dict[str, Any]:
    """Resolve Open Library Work IDs for books with ISBNs. Enables edition detection."""
    rows = await db.fetch_all("""
        SELECT id, isbn FROM books
        WHERE isbn IS NOT NULL AND length(isbn) >= 10
          AND (extra_metadata IS NULL OR NOT extra_metadata ? 'ol_work_id')
        LIMIT 10
    """)
    resolved = 0
    for r in rows:
        try:
            from brainycat.rate_limit import rate_limiter

            await rate_limiter.wait("openlibrary")
            c = get_client()
            resp = await c.get(f"https://openlibrary.org/isbn/{r['isbn']}.json")
            if resp.status_code == 200:
                data = resp.json()
                works = data.get("works", [])
                if works:
                    work_key = works[0].get("key", "").replace("/works/", "")
                    if work_key:
                        import json

                        await db.execute(
                            "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{ol_work_id}', $1::jsonb) WHERE id = $2",
                            json.dumps(work_key),
                            r["id"],
                        )
                        resolved += 1
                        rate_limiter.report_success("openlibrary")
                else:
                    rate_limiter.report_failure("openlibrary")
            else:
                rate_limiter.report_failure("openlibrary")
        except Exception:
            pass
    return {"resolved": resolved, "checked": len(rows)}


@router.get("/isbn/{isbn}/intelligence")
async def isbn_intelligence(isbn: str) -> dict[str, Any]:
    """Full ISBN intelligence: region, publisher, language, best enrichment sources."""
    from brainycat.isbn import isbn_to_publisher, isbn_to_region

    region = isbn_to_region(isbn)
    publisher = isbn_to_publisher(isbn)
    return {
        "isbn": isbn,
        "region": region,
        "publisher": publisher,
        "enrichment_priority": _enrichment_priority(region),
    }


@router.get("/isbn/{isbn}/links")
async def isbn_deep_links(isbn: str) -> dict[str, Any]:
    """Generate deterministic URLs for an ISBN across all major services."""
    from brainycat.isbn import _clean_isbn

    isbn13 = _clean_isbn(isbn)
    if not isbn13:
        return {"error": "invalid ISBN"}
    # Convert to ISBN-10 for Amazon
    isbn10 = None
    try:
        import isbnlib

        isbn10 = isbnlib.to_isbn10(isbn13)
    except Exception:
        pass

    return {
        "isbn13": isbn13,
        "isbn10": isbn10,
        "links": {
            "open_library": f"https://openlibrary.org/isbn/{isbn13}",
            "worldcat": f"https://worldcat.org/isbn/{isbn13}",
            "google_books": f"https://books.google.com/books?vid=ISBN{isbn13}",
            "amazon": f"https://amazon.com/dp/{isbn10}" if isbn10 else None,
            "abebooks": f"https://abebooks.com/servlet/BookDetailsPL?isbn={isbn13}",
            "bookshop": f"https://bookshop.org/a/0/{isbn13}",
            "goodreads": f"https://www.goodreads.com/search?q={isbn13}",
            "bnf": f"https://catalogue.bnf.fr/rechercher.do?critere1=ISBN&index1=NUM&recherche=simple&nbResultParPage=1&motRecherche={isbn13}",
        },
    }


# ── FRBR Work-level view (collapse editions) ─────────────────────────────


@router.get("/isbn/{isbn}")
async def isbn_lookup(isbn: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Deterministic book lookup by ISBN — no fuzzy search, exact match."""
    from brainycat.isbn import _clean_isbn, isbn_to_publisher, isbn_to_region

    clean = _clean_isbn(isbn)
    if not clean:
        return {"error": "invalid ISBN"}

    # Check our library first
    book = await db.fetch_one(
        """
        SELECT b.id, b.title, b.isbn, b.description, b.cover_path, b.quality_score,
               b.narrator, b.duration_seconds, b.extra_metadata,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.isbn = $1 GROUP BY b.id
    """,
        clean,
    )

    owned = bool(book)
    region = isbn_to_region(clean)
    publisher = isbn_to_publisher(clean)

    result: dict[str, Any] = {
        "isbn": clean,
        "owned": owned,
        "region": region,
        "publisher": publisher,
    }

    if book:
        result["book"] = {
            "id": str(book["id"]),
            "title": book["title"],
            "authors": book["authors"] or [],
            "description": (book["description"] or "")[:300],
            "quality_score": book["quality_score"],
            "narrator": book["narrator"],
            "duration_seconds": book["duration_seconds"],
        }

    # Deep links
    isbn10 = None
    try:
        import isbnlib

        isbn10 = isbnlib.to_isbn10(clean)
    except Exception:
        pass
    result["links"] = {
        "open_library": f"https://openlibrary.org/isbn/{clean}",
        "worldcat": f"https://worldcat.org/isbn/{clean}",
        "google_books": f"https://books.google.com/books?vid=ISBN{clean}",
        "amazon": f"https://amazon.com/dp/{isbn10}" if isbn10 else None,
    }

    return result


# ── National identifier extraction (ARK, NBN, DOI from book text) ─────────


def _enrichment_priority(region: dict | None) -> list[str]:
    """Given an ISBN region, return the optimal enrichment source order."""
    if not region:
        return ["google_books", "open_library", "amazon"]
    sources = region.get("best_sources", [])
    # Add national bibliography based on country
    countries = region.get("countries", [])
    if "FR" in countries:
        sources = ["bnf", *sources]
    elif "DE" in countries or "AT" in countries or "CH" in countries:
        sources = ["dnb", *sources]
    elif "GB" in countries or "UK" in countries:
        sources = ["british_library", *sources]
    elif "ES" in countries:
        sources = ["bne", *sources]
    elif "JP" in countries:
        sources = ["ndl", "rakuten", *sources]
    # Always include google_books as fallback
    if "google_books" not in sources:
        sources.append("google_books")
    return sources


@router.post("/books/{book_id}/deep-enrich")
async def deep_enrich_book(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Two-stage enrichment: LLM identifies → APIs verify. For hard cases."""
    from brainycat.deep_enrich import deep_enrich
    return await deep_enrich(book_id)
