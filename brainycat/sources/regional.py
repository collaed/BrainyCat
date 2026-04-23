"""Regional and specialized metadata sources — 20+ markets worldwide.

Each source is a simple async function: search(title, isbn, author) → dict.
Grouped by region for clarity.
"""

from __future__ import annotations

import re
from typing import Any

from brainycat.http_client import get_client
from brainycat.rate_limit import rate_limiter

# ── Global & Foundation ──────────────────────────────────────────────────


async def search_worldcat(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """WorldCat — which libraries hold this book, authoritative titles."""
    q = f"isbn:{isbn}" if isbn else f"ti:{title}"
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://www.worldcat.org/search?q={q}&qt=results_page", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r'<div class="name">\s*<a[^>]*>([^<]+)</a>', r.text)
            if m:
                return {"source": "worldcat", "title": m.group(1).strip()}
    except Exception:
        pass
    return None


# ── Europe ───────────────────────────────────────────────────────────────


async def search_babelio(title: str = "", author: str = "") -> dict[str, Any] | None:
    """Babelio 🇫🇷 — French social reading, ratings + reviews + tags."""
    q = f"{title} {author}".strip()
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://www.babelio.com/recherche.php?Recherche={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r'<a href="(https://www\.babelio\.com/livres/[^"]+)"[^>]*>([^<]+)</a>', r.text)
            rating = re.search(r"(\d[.,]\d+)\s*/\s*5", r.text)
            if m:
                return {
                    "source": "babelio",
                    "title": m.group(2).strip(),
                    "url": m.group(1),
                    "rating": float(rating.group(1).replace(",", ".")) if rating else None,
                }
    except Exception:
        pass
    return None


async def search_dnb(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """DNB 🇩🇪 — Deutsche Nationalbibliothek, authoritative German metadata."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(
            f"https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve&query=dc.title%3D{q}&maximumRecords=1&recordSchema=oai_dc"
        )
        if r.status_code == 200:
            from xml.etree import ElementTree as ET

            root = ET.fromstring(r.content)
            ns = {"dc": "http://purl.org/dc/elements/1.1/", "srw": "http://www.loc.gov/zing/srw/"}
            rec = root.find(".//srw:recordData", ns)
            if rec is not None:
                t = rec.findtext(".//dc:title", "", ns)
                a = rec.findtext(".//dc:creator", "", ns)
                return {"source": "dnb", "title": t, "authors": [a] if a else []}
    except Exception:
        pass
    return None


async def search_bnf(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """BnF 🇫🇷 — Bibliothèque nationale de France via SPARQL. Authoritative French metadata."""
    query = isbn or title
    if not query:
        return None
    try:
        c = get_client()
        await rate_limiter.wait("default")
        sparql = f"""SELECT ?title ?author ?date ?publisher WHERE {{
            ?book dcterms:title ?title .
            OPTIONAL {{ ?book dcterms:creator/foaf:name ?author }}
            OPTIONAL {{ ?book dcterms:date ?date }}
            OPTIONAL {{ ?book dcterms:publisher/foaf:name ?publisher }}
            FILTER(CONTAINS(LCASE(?title), LCASE("{query}")))
        }} LIMIT 3"""
        r = await c.get(
            "https://data.bnf.fr/sparql", params={"query": sparql, "format": "json"}, headers={"Accept": "application/sparql-results+json"}
        )
        if r.status_code == 200:
            bindings = r.json().get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                return {
                    "source": "bnf",
                    "title": b.get("title", {}).get("value"),
                    "authors": [b["author"]["value"]] if "author" in b else [],
                    "publisher": b.get("publisher", {}).get("value"),
                    "date": b.get("date", {}).get("value"),
                }
    except Exception:
        pass
    return None


async def search_fantastic_fiction(title: str = "", author: str = "") -> dict[str, Any] | None:
    """Fantastic Fiction 🇬🇧 — best series ordering for English fiction."""
    q = f"{title} {author}".strip()
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://www.fantasticfiction.com/search/?searchfor=book&keywords={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r'<a href="(/[a-z]/[^"]+)"[^>]*>([^<]+)</a>.*?<span[^>]*>([^<]*)</span>', r.text, re.DOTALL)
            series_m = re.search(r'<a href="/[a-z]/[^"]*series[^"]*">([^<]+)</a>\s*#?(\d+)?', r.text)
            if m:
                return {
                    "source": "fantastic_fiction",
                    "title": m.group(2).strip(),
                    "author": m.group(3).strip(),
                    "series": series_m.group(1) if series_m else None,
                    "series_index": int(series_m.group(2)) if series_m and series_m.group(2) else None,
                }
    except Exception:
        pass
    return None


async def search_thalia(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """Thalia 🇩🇪🇦🇹🇨🇭 — German/Austrian/Swiss bookstore, reviews + hi-res covers."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://www.thalia.de/suche?sq={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r'"name"\s*:\s*"([^"]+)".*?"author"\s*:\s*"([^"]*)"', r.text)
            if m:
                return {"source": "thalia", "title": m.group(1), "authors": [m.group(2)] if m.group(2) else []}
    except Exception:
        pass
    return None


async def search_bol_nl(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """BOL.com 🇳🇱🇧🇪 — Dutch/Belgian bookstore metadata."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://www.bol.com/nl/nl/s/?searchtext={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r'data-test="product-title"[^>]*>([^<]+)', r.text)
            if m:
                return {"source": "bol_nl", "title": m.group(1).strip()}
    except Exception:
        pass
    return None


async def search_skoob(title: str = "", author: str = "") -> dict[str, Any] | None:
    """Skoob 🇧🇷 — Brazilian Goodreads (5M+ users), ratings + shelves."""
    q = f"{title} {author}".strip()
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(
            f"https://www.skoob.com.br/livro/lista?tipo=livro&limite=3&texto={q}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        if r.status_code == 200:
            data = r.json() if "json" in r.headers.get("content-type", "") else {}
            if isinstance(data, list) and data:
                return {"source": "skoob", "title": data[0].get("nome"), "rating": data[0].get("nota")}
    except Exception:
        pass
    return None


# ── Spanish & Latin America ──────────────────────────────────────────────


async def search_casa_del_libro(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """Casa del Libro 🇪🇸 — Spain/Latin America primary bookstore."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://www.casadellibro.com/busqueda-generica?busqueda={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            m = re.search(r'<a[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</a>', r.text)
            if m:
                return {"source": "casa_del_libro", "title": m.group(1).strip()}
    except Exception:
        pass
    return None


# ── East Asia ────────────────────────────────────────────────────────────


async def search_rakuten(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """Rakuten Books 🇯🇵 — Japanese books + manga."""
    try:
        c = get_client()
        await rate_limiter.wait("default")
        params = {"applicationId": "1", "format": "json", "hits": 3}
        if isbn:
            params["isbn"] = isbn
        else:
            params["title"] = title
        r = await c.get("https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404", params=params)
        if r.status_code == 200:
            items = r.json().get("Items", [])
            if items:
                item = items[0].get("Item", {})
                return {
                    "source": "rakuten",
                    "title": item.get("title"),
                    "authors": [item.get("author", "")],
                    "isbn": item.get("isbn"),
                    "cover_url": item.get("largeImageUrl"),
                }
    except Exception:
        pass
    return None


async def search_douban(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """Douban Books 🇨🇳 — Chinese Goodreads (200M+ users)."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://book.douban.com/j/subject_suggest?q={q}", headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            if data:
                return {
                    "source": "douban",
                    "title": data[0].get("title"),
                    "authors": [data[0].get("author_name", "")],
                    "url": data[0].get("url"),
                }
    except Exception:
        pass
    return None


# ── Manga & Comics ───────────────────────────────────────────────────────


async def search_myanimelist(title: str = "") -> dict[str, Any] | None:
    """MyAnimeList 🌍 — manga metadata, series ordering."""
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://api.jikan.moe/v4/manga?q={title}&limit=3")
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                m = data[0]
                return {
                    "source": "myanimelist",
                    "title": m.get("title"),
                    "title_japanese": m.get("title_japanese"),
                    "score": m.get("score"),
                    "chapters": m.get("chapters"),
                    "volumes": m.get("volumes"),
                    "status": m.get("status"),
                    "genres": [g["name"] for g in m.get("genres", [])],
                }
    except Exception:
        pass
    return None


async def search_comicvine(title: str = "") -> dict[str, Any] | None:
    """ComicVine 🌍 — comic/graphic novel issue-level metadata."""
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(f"https://comicvine.gamespot.com/api/search/?api_key=&format=json&resources=volume&query={title}&limit=3")
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                v = results[0]
                return {
                    "source": "comicvine",
                    "title": v.get("name"),
                    "publisher": v.get("publisher", {}).get("name"),
                    "issue_count": v.get("count_of_issues"),
                    "start_year": v.get("start_year"),
                }
    except Exception:
        pass
    return None


# ── National Bibliographies (Legal Deposit — most authoritative) ──────────


async def search_british_library(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """British Library 🇬🇧 — UK legal deposit, every UK publication."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(
            "https://bnb.data.bl.uk/sparql",
            params={
                "query": f'SELECT ?title ?author WHERE {{ ?book <http://purl.org/dc/terms/title> ?title . OPTIONAL {{ ?book <http://purl.org/dc/terms/creator> ?author }} FILTER(CONTAINS(LCASE(?title), LCASE("{q}"))) }} LIMIT 3',
                "format": "json",
            },
            headers={"Accept": "application/sparql-results+json"},
        )
        if r.status_code == 200:
            bindings = r.json().get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                return {
                    "source": "british_library",
                    "title": b.get("title", {}).get("value"),
                    "authors": [b["author"]["value"]] if "author" in b else [],
                }
    except Exception:
        pass
    return None


async def search_bne(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """BNE 🇪🇸 — Biblioteca Nacional de España, every Spanish publication."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(
            "https://datos.bne.es/sparql",
            params={
                "query": f'SELECT ?title ?author WHERE {{ ?book <http://purl.org/dc/elements/1.1/title> ?title . OPTIONAL {{ ?book <http://purl.org/dc/elements/1.1/creator> ?author }} FILTER(CONTAINS(LCASE(?title), LCASE("{q}"))) }} LIMIT 3',
                "format": "json",
            },
            headers={"Accept": "application/sparql-results+json"},
        )
        if r.status_code == 200:
            bindings = r.json().get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                return {
                    "source": "bne",
                    "title": b.get("title", {}).get("value"),
                    "authors": [b["author"]["value"]] if "author" in b else [],
                }
    except Exception:
        pass
    return None


async def search_ndl(title: str = "", isbn: str = "") -> dict[str, Any] | None:
    """NDL 🇯🇵 — National Diet Library of Japan."""
    q = isbn or title
    try:
        c = get_client()
        await rate_limiter.wait("default")
        r = await c.get(
            f"https://ndlsearch.ndl.go.jp/api/sru?operation=searchRetrieve&query=title%3D{q}&maximumRecords=3&recordSchema=dcndl_simple"
        )
        if r.status_code == 200:
            from xml.etree import ElementTree as ET

            root = ET.fromstring(r.content)
            ns = {"dc": "http://purl.org/dc/elements/1.1/", "srw": "http://www.loc.gov/zing/srw/"}
            rec = root.find(".//srw:recordData", ns)
            if rec is not None:
                t = rec.findtext(".//dc:title", "", ns)
                a = rec.findtext(".//dc:creator", "", ns)
                if t:
                    return {"source": "ndl", "title": t, "authors": [a] if a else []}
    except Exception:
        pass
    return None
