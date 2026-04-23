"""Author authority sources — ISNI, VIAF for author disambiguation.

ISNI: International Standard Name Identifier — unique author IDs
VIAF: Virtual International Authority File — links names across languages
"""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client


async def search_viaf(name: str) -> list[dict[str, Any]]:
    """Search VIAF for author authority records. Links names across languages."""
    try:
        client = get_client()
        resp = await client.get(
            "https://viaf.org/viaf/search",
            params={
                "query": f'local.personalNames all "{name}"',
                "sortKeys": "holdingscount",
                "maximumRecords": 5,
                "httpAccept": "application/json",
            },
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        records = data.get("searchRetrieveResponse", {}).get("records", [])
        results = []
        for rec in records:
            rd = rec.get("record", {}).get("recordData", {})
            viaf_id = rd.get("viafID", "")
            # Get all name forms
            names = []
            main = rd.get("mainHeadings", {}).get("data", [])
            if isinstance(main, dict):
                main = [main]
            for m in main:
                text = m.get("text", "")
                sources = m.get("sources", {}).get("s", [])
                if isinstance(sources, str):
                    sources = [sources]
                names.append({"name": text, "sources": sources})
            results.append(
                {
                    "viaf_id": viaf_id,
                    "url": f"https://viaf.org/viaf/{viaf_id}",
                    "names": names,
                    "name_count": len(names),
                }
            )
        return results
    except Exception:
        return []


async def search_isni(name: str) -> list[dict[str, Any]]:
    """Search ISNI for author identifiers."""
    try:
        client = get_client()
        resp = await client.get(
            "https://isni.org/isni/search",
            params={"query": name, "format": "json"},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return []
        # ISNI doesn't have a clean JSON API — parse what we can
        data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
        return data.get("results", [])
    except Exception:
        return []


async def search_inventaire(query: str) -> list[dict[str, Any]]:
    """Search Inventaire — Wikidata-backed book database."""
    try:
        client = get_client()
        resp = await client.get(
            "https://inventaire.io/api/search",
            params={"types": "works", "search": query, "limit": 10, "lang": "en"},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {
                "source": "inventaire",
                "title": r.get("label", ""),
                "description": r.get("description", ""),
                "uri": r.get("uri", ""),
                "url": f"https://inventaire.io/entity/{r.get('uri', '')}",
                "image": r.get("image", ""),
            }
            for r in data.get("results", [])
        ]
    except Exception:
        return []


async def search_bookbrainz(query: str) -> list[dict[str, Any]]:
    """Search BookBrainz — MusicBrainz for books."""
    try:
        client = get_client()
        resp = await client.get(
            f"https://bookbrainz.org/search/search?q={query}&type=Edition",
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {
                "source": "bookbrainz",
                "title": r.get("defaultAlias", {}).get("name", ""),
                "bbid": r.get("bbid", ""),
                "url": f"https://bookbrainz.org/edition/{r.get('bbid', '')}",
                "type": r.get("type", ""),
            }
            for r in data.get("results", [])[:10]
        ]
    except Exception:
        return []
