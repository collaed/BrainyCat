"""Library-wide passes applied after per-file extraction: reject ISBNs shared by unrelated titles
(placeholder/template values), then optionally verify against an external source (Open Library).

Mutates `rows` in place (list of scan.py's row dicts) so it can be reused by scan.py and by ad-hoc
re-scoring of an existing CSV without re-extracting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from brainycat.identify import Candidate, apply_verification, reject_shared, resolve, verify

if TYPE_CHECKING:
    from pathlib import Path


def postprocess(rows: list[dict[str, str]], lookup_cache: Path | None = None) -> None:
    cands = {r["file"]: c for r in rows if (c := resolve(dict(x.split("=") for x in r["all_isbns"].split(";") if x)))}
    titles = {r["file"]: r["title"] or r["fn_title"] for r in rows}
    by_file = {r["file"]: r for r in rows}
    for k in reject_shared(cands, titles):
        by_file[k]["confidence"] = "possible"

    if not lookup_cache:
        return
    from tests.golden.ol import lookup_many

    recs = lookup_many([r["isbn"] for r in rows if r["isbn"]], lookup_cache)
    for r in rows:
        if not r["isbn"]:
            continue
        authors = [a for a in r["authors"].split("; ") if a] or ([r["fn_author"]] if r["fn_author"] else [])
        r["lookup"] = verdict = verify(r["title"] or r["fn_title"], authors, recs.get(r["isbn"]))
        if r["confidence"] != "possible" or verdict == "verified":  # a shared-ISBN reject stays rejected unless confirmed
            c = Candidate(r["isbn"], r["method"], r["confidence"])
            apply_verification(c, verdict)
            r["confidence"] = c.confidence
