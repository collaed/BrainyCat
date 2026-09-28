"""Translation linking via Wikidata.

Data model on Wikidata: a specific-language EDITION item carries P629 ("edition or translation of")
pointing to an abstract WORK item; the work item's own P407 gives the work's original language. All
editions sharing that P629 target are siblings — different-language editions of the same book — and
we find them with one SPARQL query. The sibling whose language matches the work's P407 is "the
original"; the rest are translations of it.

Manual, per-book trigger only (not a background loop) — stays a good citizen of Wikidata's public
endpoints rather than sweeping the whole library against them unprompted.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client

_UA = {"User-Agent": "BrainyCat/1.0 (self-hosted personal library app; no contact on file)"}
_WD_API = "https://www.wikidata.org/w/api.php"
_WD_SPARQL = "https://query.wikidata.org/sparql"


async def _wd_search(title: str, limit: int = 5) -> list[dict[str, Any]]:
    resp = await get_client().get(
        _WD_API,
        params={"action": "wbsearchentities", "search": title, "language": "en", "format": "json", "limit": limit, "type": "item"},
        headers=_UA,
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("search", [])


async def _wd_get_entity(qid: str) -> dict[str, Any] | None:
    resp = await get_client().get(
        _WD_API,
        params={"action": "wbgetentities", "ids": qid, "format": "json", "props": "claims|labels", "languages": "en"},
        headers=_UA,
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("entities", {}).get(qid)


def _claim_target(entity: dict[str, Any], prop: str) -> str | None:
    claims = entity.get("claims", {}).get(prop)
    if not claims:
        return None
    try:
        return claims[0]["mainsnak"]["datavalue"]["value"]["id"]
    except (KeyError, IndexError):
        return None


async def _pick_best_candidate(title: str, author: str | None) -> dict[str, Any] | None:
    """Search Wikidata for the book; if we have an author, prefer the candidate whose P50 (author)
    label matches — plain title search alone returns far too many unrelated same-title works."""
    candidates = await _wd_search(title)
    if not candidates:
        return None
    if not author:
        return candidates[0]

    author_lower = author.lower()
    for c in candidates:
        entity = await _wd_get_entity(c["id"])
        if not entity:
            continue
        author_qids = [claim["mainsnak"]["datavalue"]["value"]["id"] for claim in entity.get("claims", {}).get("P50", []) if claim.get("mainsnak", {}).get("datavalue")]
        if not author_qids:
            continue
        labels = await _wd_get_labels(author_qids)
        if any(author_lower in label.lower() or label.lower() in author_lower for label in labels.values()):
            return c
    return candidates[0]


async def _wd_get_labels(qids: list[str]) -> dict[str, str]:
    if not qids:
        return {}
    resp = await get_client().get(
        _WD_API,
        params={"action": "wbgetentities", "ids": "|".join(qids), "format": "json", "props": "labels", "languages": "en"},
        headers=_UA,
        timeout=10,
    )
    if resp.status_code != 200:
        return {}
    entities = resp.json().get("entities", {})
    return {qid: e.get("labels", {}).get("en", {}).get("value", qid) for qid, e in entities.items()}


async def _find_siblings(work_qid: str) -> list[dict[str, Any]]:
    query = f"""
    SELECT ?edition ?editionLabel ?lang ?langLabel WHERE {{
      ?edition wdt:P629 wd:{work_qid} .
      OPTIONAL {{ ?edition wdt:P407 ?lang . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 50
    """
    resp = await get_client().get(_WD_SPARQL, params={"query": query, "format": "json"}, headers=_UA, timeout=15)
    if resp.status_code != 200:
        return []
    out = []
    for b in resp.json().get("results", {}).get("bindings", []):
        edition_uri = b.get("edition", {}).get("value", "")
        out.append(
            {
                "qid": edition_uri.rsplit("/", 1)[-1],
                "title": b.get("editionLabel", {}).get("value"),
                "language_qid": b.get("lang", {}).get("value", "").rsplit("/", 1)[-1] or None,
                "language": b.get("langLabel", {}).get("value"),
            }
        )
    return out


async def find_translations(title: str, author: str | None = None) -> dict[str, Any]:
    """Resolve a title (+ optional author) to its Wikidata work, and return all sibling editions —
    the one matching the work's original language (P407) flagged as `is_original`."""
    candidate = await _pick_best_candidate(title, author)
    if not candidate:
        return {"ok": False, "reason": "no Wikidata match for this title"}

    entity = await _wd_get_entity(candidate["id"])
    if not entity:
        return {"ok": False, "reason": "could not fetch Wikidata entity"}

    work_qid = _claim_target(entity, "P629") or candidate["id"]
    work_entity = await _wd_get_entity(work_qid)
    original_lang_qid = _claim_target(work_entity, "P407") if work_entity else None

    siblings = await _find_siblings(work_qid)
    for s in siblings:
        s["is_original"] = bool(original_lang_qid) and s["language_qid"] == original_lang_qid

    return {"ok": True, "book_qid": candidate["id"], "work_qid": work_qid, "siblings": siblings}


async def link_translations(book_id: str) -> dict[str, Any]:
    """Look up this book's translations/original on Wikidata and store what we found:
    - books.wikidata_qid always set to the matched edition, so a repeat lookup can skip the search.
    - books.translation_of_book_id set only if the original edition is also in THIS library
      (matched by title, best-effort).
    - extra_metadata.translations holds the full sibling list either way, for display even when the
      original isn't in the library."""
    book = await fetch_one("SELECT title, extra_metadata FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return {"error": "not found"}

    author_row = await fetch_one(
        "SELECT a.name FROM authors a JOIN books_authors ba ON ba.author_id = a.id WHERE ba.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    author = author_row["name"] if author_row else None

    result = await find_translations(book["title"], author)
    if not result.get("ok"):
        return result

    import json as _json

    await execute(
        "UPDATE books SET wikidata_qid = $1, extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $2::jsonb WHERE id = $3",
        result["book_qid"],
        _json.dumps({"translations": {"work_qid": result["work_qid"], "siblings": result["siblings"]}}),
        UUID(book_id),
    )

    # If the original edition's title matches another book already in this library, link them for real.
    original = next((s for s in result["siblings"] if s.get("is_original")), None)
    linked_book_id = None
    if original and original.get("title") and original["title"] != book["title"]:
        match = await fetch_one("SELECT id FROM books WHERE title = $1 AND id != $2", original["title"], UUID(book_id))
        if match:
            await execute("UPDATE books SET translation_of_book_id = $1 WHERE id = $2", match["id"], UUID(book_id))
            linked_book_id = str(match["id"])

    return {"ok": True, "siblings": result["siblings"], "linked_to_book_id": linked_book_id}


async def get_translation_info(book_id: str) -> dict[str, Any]:
    """What's already known for this book — original + sibling translations, and whether the
    original is in this library (for a UI 'jump to original' link)."""
    row = await fetch_one(
        "SELECT b.extra_metadata, b.translation_of_book_id, o.title as original_title FROM books b "
        "LEFT JOIN books o ON o.id = b.translation_of_book_id WHERE b.id = $1",
        UUID(book_id),
    )
    if not row:
        return {}
    translations = (row["extra_metadata"] or {}).get("translations")

    in_library_translations = await fetch_all(
        "SELECT id, title FROM books WHERE translation_of_book_id = $1", UUID(book_id)
    )

    return {
        "translations": translations,
        "translation_of_book_id": str(row["translation_of_book_id"]) if row["translation_of_book_id"] else None,
        "original_title": row["original_title"],
        "in_library_translations": [{"id": str(r["id"]), "title": r["title"]} for r in in_library_translations],
    }
