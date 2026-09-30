"""Readarr integration — search for a book and hand it to Readarr to find + download.

Config: BRAINYCAT_READARR_URL + BRAINYCAT_READARR_API_KEY (required), plus optionally
BRAINYCAT_READARR_ROOT_FOLDER / BRAINYCAT_READARR_QUALITY_PROFILE_ID (auto-detected from Readarr's
own config — the first of each — if left unset).

BrainyCat only triggers the add + search; the actual download (indexers, download client) and the
file landing in BrainyCat's incoming folder both depend on Readarr's own configuration — specifically
its root folder needs to be (or be symlinked to) BrainyCat's incoming directory for the download to
actually show up here once Readarr finishes.
"""

from __future__ import annotations

from typing import Any


def _client_config() -> tuple[str, str] | None:
    """Read the configured Readarr URL/API key, or None if not configured. Internal helper used by the other functions in this module."""
    from brainycat.config import settings

    url = (settings.readarr_url or "").rstrip("/")
    key = settings.readarr_api_key or ""
    if not url or not key:
        return None
    return url, key


async def search_readarr(query: str) -> dict[str, Any]:
    """Search Readarr for a book — returns the raw Readarr search results (each one has enough
    fields to hand straight back to add_to_readarr)."""
    import httpx

    cfg = _client_config()
    if not cfg:
        return {"error": "Readarr not configured (set BRAINYCAT_READARR_URL + BRAINYCAT_READARR_API_KEY)"}
    url, key = cfg

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{url}/api/v1/search", params={"term": query}, headers={"X-Api-Key": key})
    except httpx.RequestError as e:
        return {"error": f"couldn't reach Readarr: {e}"}
    if r.status_code != 200:
        return {"error": f"Readarr returned {r.status_code}: {r.text[:300]}"}

    results = []
    for item in r.json()[:15]:
        book = item.get("book") or item  # some Readarr versions nest under "book", some don't
        author = book.get("author") or item.get("author") or {}
        results.append(
            {
                "title": book.get("title"),
                "author": author.get("authorName") or author.get("name"),
                "year": (book.get("releaseDate") or "")[:4] or None,
                "overview": (book.get("overview") or "")[:300],
                "book": book,  # pass straight back to add_to_readarr unmodified
            }
        )
    return {"results": results}


async def _first(url: str, key: str, path: str) -> dict[str, Any] | None:
    """GET a Readarr endpoint and return its first list item, or None. Internal helper used by `add_to_readarr` for root folder/quality profile auto-detection."""
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{url}{path}", headers={"X-Api-Key": key})
    if r.status_code == 200 and r.json():
        return r.json()[0]
    return None


async def add_to_readarr(book: dict[str, Any]) -> dict[str, Any]:
    """Add one specific book (the `book` field from a search_readarr result, unmodified) to
    Readarr's library, monitored, and trigger an immediate search for it."""
    import httpx

    from brainycat.config import settings

    cfg = _client_config()
    if not cfg:
        return {"error": "Readarr not configured (set BRAINYCAT_READARR_URL + BRAINYCAT_READARR_API_KEY)"}
    url, key = cfg
    headers = {"X-Api-Key": key}

    root_folder = settings.readarr_root_folder
    if not root_folder:
        rf = await _first(url, key, "/api/v1/rootfolder")
        if not rf:
            return {"error": "Readarr has no root folder configured — set one in Readarr, or BRAINYCAT_READARR_ROOT_FOLDER"}
        root_folder = rf["path"]

    quality_profile_id = settings.readarr_quality_profile_id
    if not quality_profile_id:
        qp = await _first(url, key, "/api/v1/qualityprofile")
        if not qp:
            return {"error": "Readarr has no quality profile configured"}
        quality_profile_id = qp["id"]

    payload = dict(book)
    payload["rootFolderPath"] = root_folder
    payload["qualityProfileId"] = int(quality_profile_id)
    payload["monitored"] = True
    payload["addOptions"] = {"searchForNewBook": True}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{url}/api/v1/book", json=payload, headers=headers)
    except httpx.RequestError as e:
        return {"error": f"couldn't reach Readarr: {e}"}
    if r.status_code in (200, 201):
        return {"ok": True, "title": payload.get("title")}
    return {"error": f"Readarr add failed ({r.status_code}): {r.text[:300]}"}
