"""Open Library ISBN lookup with an on-disk cache (harness side; production uses brainycat.sources).

Uses /isbn/{isbn}.json (proven live in evaluate.py) rather than the bulk /api/books endpoint, which
404s as of 2026-09 — kept as one lesson: don't trust an API shape without hitting it first.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import httpx

from brainycat.identify import Record

if TYPE_CHECKING:
    from pathlib import Path

_UA = {"User-Agent": "brainycat-golden/0.1"}


def _get(c: httpx.Client, url: str) -> dict | None:
    for _ in range(3):
        try:
            r = c.get(url, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return None


def lookup_many(isbns: list[str], cache_path: Path, author_cache_path: Path | None = None) -> dict[str, Record | None]:
    cache: dict[str, dict | None] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    author_cache_path = author_cache_path or cache_path.with_name(cache_path.stem + "_authors.json")
    authors: dict[str, str | None] = json.loads(author_cache_path.read_text()) if author_cache_path.exists() else {}
    todo = [i for i in dict.fromkeys(isbns) if i and i not in cache]

    with httpx.Client(headers=_UA, timeout=30) as c:
        for n, isbn in enumerate(todo, 1):
            edition = _get(c, f"https://openlibrary.org/isbn/{isbn}.json")
            time.sleep(0.2)
            if edition is None:
                cache[isbn] = None
            else:
                names = []
                for key in [a.get("key") for a in edition.get("authors", []) if a.get("key")][:2]:
                    if key not in authors:
                        rec = _get(c, f"https://openlibrary.org{key}.json")
                        authors[key] = rec.get("name") if rec else None
                        time.sleep(0.2)
                    if authors[key]:
                        names.append(authors[key])
                cache[isbn] = {"title": edition.get("title", ""), "authors": names}
            if n % 50 == 0:
                cache_path.write_text(json.dumps(cache))
                author_cache_path.write_text(json.dumps(authors))
    cache_path.write_text(json.dumps(cache))
    author_cache_path.write_text(json.dumps(authors))
    return {i: (Record(**cache[i]) if cache.get(i) else None) for i in isbns}
