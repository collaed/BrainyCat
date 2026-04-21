"""Wikidata SPARQL — structured book metadata."""

from __future__ import annotations

from typing import Any

import httpx

SPARQL_URL = "https://query.wikidata.org/sparql"


async def search_by_isbn(isbn: str) -> dict[str, Any] | None:
    """Query Wikidata for book metadata by ISBN."""
    query = f"""
    SELECT ?book ?bookLabel ?genreLabel ?awardLabel ?langLabel ?wpArticle WHERE {{
      ?book wdt:P212 "{isbn}" .
      OPTIONAL {{ ?book wdt:P136 ?genre }}
      OPTIONAL {{ ?book wdt:P166 ?award }}
      OPTIONAL {{ ?book wdt:P407 ?lang }}
      OPTIONAL {{ ?wpArticle schema:about ?book ; schema:isPartOf <https://en.wikipedia.org/> }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
    }} LIMIT 10
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(SPARQL_URL, params={"query": query, "format": "json"})
        if resp.status_code != 200:
            return None
        data = resp.json()

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None

    genres = list({b["genreLabel"]["value"] for b in bindings if "genreLabel" in b})
    awards = list({b["awardLabel"]["value"] for b in bindings if "awardLabel" in b})
    lang = next((b["langLabel"]["value"] for b in bindings if "langLabel" in b), None)
    wp = next((b["wpArticle"]["value"] for b in bindings if "wpArticle" in b), None)

    return {
        "source": "wikidata",
        "genres": genres,
        "awards": awards,
        "original_language": lang,
        "wikipedia_url": wp,
    }
