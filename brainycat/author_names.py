"""Author name parsing — split a compound multi-author string into individual names, and normalize
"Lastname, Firstname" to "Firstname Lastname" so both forms of the same person compare equal.

Author name parsing has no fully reliable general solution (this module is a heuristic, not a
parser for a formal grammar) — see docs/known-issues.md for the cases it still gets wrong.
"""

from __future__ import annotations

import re
from typing import Any

# Delimiters that never appear inside a single western name — safe to split on unconditionally.
_STRONG_SPLIT_RE = re.compile(r"\s*;\s*|\s*&\s*|\s+and\s+|\s+et\s+", re.IGNORECASE)
# A trailing Library-of-Congress-style birth/death year annotation: ", 1935-" or ", 19..-1998" etc.
_TRAILING_YEAR_RE = re.compile(r",\s*\d{2,4}[.\-]{1,3}\d{0,4}-?\s*$")
# A bracketed re-statement of the name, e.g. "Martha Alderson [Alderson, Martha]" — redundant, and
# its internal comma breaks the main split logic if left in.
_BRACKET_RE = re.compile(r"\s*\[[^\]]*\]\s*")
# MARC-relator / role words and professional suffixes that show up as their own comma-part — not a
# name, and must not be reordered into one ("Laura L. Smith, PhD" must not become "PhD Laura L. Smith").
_NON_NAME_TOKENS = {
    "author",
    "illustrator",
    "editor",
    "translator",
    "verfasser",
    "compiler",
    "narrator",
    "photographer",
    "phd",
    "ph.d",
    "ph.d.",
    "md",
    "m.d.",
    "esq",
    "esq.",
    "jr",
    "jr.",
    "sr",
    "sr.",
}


def _strip_trailing_year(s: str) -> str:
    """Remove a trailing publication-year fragment from a name string. Internal helper used by `_split_comma_segment`."""
    return _TRAILING_YEAR_RE.sub("", s).strip()


def _split_comma_segment(seg: str) -> list[str]:
    """A segment with no strong (;/&/and/et) delimiter may still hide multiple authors behind
    commas — either one 'Last, First' name, or a list of names. Word-count shape decides which."""
    seg = _BRACKET_RE.sub("", seg)
    seg = _strip_trailing_year(seg)
    parts = [p.strip().rstrip(".") for p in seg.split(",") if p.strip()]
    # Drop role/suffix tokens entirely — they're not a name and shouldn't count toward the shape.
    parts = [p for p in parts if p.lower() not in _NON_NAME_TOKENS]
    if len(parts) <= 1:
        return [parts[0]] if parts else []

    word_counts = [len(p.split()) for p in parts]

    if len(parts) == 2 and not all(c >= 2 for c in word_counts):
        # "Lamarche, Caroline" (1,1) or "de la Cruz, Valeria" (3,1) — one person, Last/First order,
        # even with a multi-word surname. Only treat 2 comma-parts as 2 separate authors when BOTH
        # already look like a full "Firstname Lastname" on their own (below).
        return [f"{parts[1]} {parts[0]}"]

    if all(c >= 2 for c in word_counts):
        # "Konrad Banachewicz, Luca Massaron, Anthony Goldbloom" — already Firstname Lastname each.
        return parts

    if len(parts) >= 4 and len(parts) % 2 == 0:
        # "Christensen, Paulina, Fox, Anne, Foster, Wendy" (or "Mairowitz, David Zane, Appignanesi,
        # Richard, Crumb, R." — a first name isn't always one word) — repeated Last,First pairs
        # chained by comma. An even part count this large is the chained-pairs shape far more often
        # than it's a list of mononym authors, so pair consecutively regardless of word count.
        return [f"{parts[i + 1]} {parts[i]}" for i in range(0, len(parts), 2)]

    # Ambiguous shape (mixed word counts, odd part count) — best effort, no reordering.
    return parts


def split_authors(raw: str | None) -> list[str]:
    """Split a possibly-compound author string into individual, deduplicated author names."""
    if not raw or not raw.strip():
        return []

    names: list[str] = []
    for segment in _STRONG_SPLIT_RE.split(raw):
        segment = segment.strip()
        if not segment:
            continue
        names.extend(_split_comma_segment(segment))

    seen: set[str] = set()
    result = []
    for name in names:
        name = name.strip().strip(",;")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        result.append(name)
    return result


# ---------------------------------------------------------------------------
# Retroactive cleanup of existing compound/misordered author rows
# ---------------------------------------------------------------------------


async def find_compound_authors() -> list[dict[str, Any]]:
    """Authors table rows whose name is a compound string or "Last, First" order — candidates for
    apply_compound_cleanup(). Review-first, not auto-applied: word-count heuristics can misfire on
    unusual names (see docs/known-issues.md)."""
    from brainycat.db import fetch_all

    rows = await fetch_all("SELECT id, name FROM authors WHERE name ~ '[,&;]| and | et '")
    candidates = []
    for r in rows:
        split = split_authors(r["name"])
        if split != [r["name"]]:
            candidates.append({"author_id": str(r["id"]), "original": r["name"], "split_into": split})
    return candidates


async def apply_compound_cleanup(author_id: str, split_into: list[str]) -> dict[str, Any]:
    """Replace one compound/misordered author with the given individual names, relinking every book
    that referenced it, then remove the old author row — one transaction, so a crash partway through
    can't leave a book with its old author link gone and the new one not yet in place."""
    from uuid import UUID

    from brainycat.db import fetch_all, transaction

    books = await fetch_all("SELECT book_id FROM books_authors WHERE author_id = $1", UUID(author_id))
    async with transaction() as conn:
        for name in split_into:
            await conn.execute("INSERT INTO authors (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", name)
            new_row = await conn.fetchrow("SELECT id FROM authors WHERE name = $1", name)
            if new_row:
                for b in books:
                    await conn.execute(
                        "INSERT INTO books_authors (book_id, author_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        b["book_id"],
                        new_row["id"],
                    )
        await conn.execute("DELETE FROM books_authors WHERE author_id = $1", UUID(author_id))
        await conn.execute("DELETE FROM authors WHERE id = $1", UUID(author_id))
    return {"ok": True, "book_count": len(books), "split_into": split_into}
