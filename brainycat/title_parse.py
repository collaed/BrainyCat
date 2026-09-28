"""Parse structured metadata out of filename-derived titles.

A large fraction of this library's messy titles are actually Anna's Archive or libgen.li export
filenames used verbatim as the title, e.g.:

    "21b50b4d Autism Your Questions Answered -- Romeo Vitelli -- 1, 2024 -- Bloomsbury Publishing
     USA -- 9781440881565 -- 1e9c3d90f7395ba6b878c4b76e431e7a -- Anna's Archive"

    "20da7613 Héctor García, Francesc Miralles - La méthode Ikigai (2018, Solar) - libgen.li"

These aren't noise to search around — they're structured records (title -- author -- year/place --
publisher -- isbn -- content-hash -- site-name) that can be parsed directly, no external API call
needed, and no rate limit to wait on. Even when no known structure matches, stripping the leading
content-hash prefix and trailing site-name noise still produces a much better lookup query than the
raw string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from brainycat.isbn import _clean_isbn

_HEX8_PREFIX_RE = re.compile(r"^[0-9a-f]{8}\s+")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_ANNA_SUFFIX_RE = re.compile(r"\s*--\s*Anna[’']s Archive\s*$", re.IGNORECASE)  # noqa: RUF001 — both apostrophe styles appear in real data
_LIBGEN_SUFFIX_RE = re.compile(r"\s*-\s*libgen\.\w+\s*$", re.IGNORECASE)
_YEAR_PUBLISHER_PAREN_RE = re.compile(r"\((\d{4}),\s*([^)]+)\)\s*$")
_LEADING_ISBN_RE = re.compile(r"^(97[89][\d\-]{9,15}|\d{9}[\dXx])\s+(.+)$")
_LEAKED_EXT_RE = re.compile(r"\s+\S{1,6}\.(indd|qxd|docx?|BAT|ai|psd)\s*$", re.IGNORECASE)
_BRACKET_SERIES_RE = re.compile(r"^\[[^\]]+\]\s*")
_PLACE_RE = re.compile(r"^[A-ZÀ-Ý][\w'\-]*(,\s*[A-ZÀ-Ý][\w'\-]*)+$")
_ISBN_SHAPE_RE = re.compile(r"^[\d\-\sXx]{9,17}$")


@dataclass
class ParsedTitle:
    title: str
    author: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    year: str | None = None
    confidence: str = "low"  # "high": a known structured pattern matched. "medium"/"low": best-effort noise strip.


def _looks_like_year_or_place(s: str) -> bool:
    s = s.strip()
    if len(s) > 60:
        return False
    if re.search(r"\b(19|20)\d{2}\b", s):
        return True
    return bool(_PLACE_RE.match(s))


def _pop_trailing_metadata(parts: list[str]) -> tuple[str | None, str | None, str | None]:
    """Classify and discard trailing segments (isbn / year-or-place / publisher) from an
    Anna's-Archive-style ' -- '-joined list, stopping once only title+author (2 parts) remain."""
    isbn = publisher = year = None
    while len(parts) > 2:
        tail = parts[-1]
        tail_isbn = _clean_isbn(re.sub(r"[^0-9Xx]", "", tail)) if _ISBN_SHAPE_RE.match(tail) else None
        if tail_isbn and not isbn:
            isbn = tail_isbn
            parts.pop()
            continue
        if _looks_like_year_or_place(tail):
            if not year:
                ym = re.search(r"(19|20)\d{2}", tail)
                if ym:
                    year = ym.group(0)
            parts.pop()
            continue
        if not publisher:
            publisher = tail
            parts.pop()
            continue
        break
    return isbn, publisher, year


def parse_title(raw: str) -> ParsedTitle:
    """Best-effort structured parse of a filename-derived title. Always returns a usable title
    (falls back to a noise-stripped version of the input) — check `.confidence` before trusting
    the other fields for an automatic write."""
    s = raw.strip()
    s = _HEX8_PREFIX_RE.sub("", s)

    isbn_from_prefix = None
    m = _LEADING_ISBN_RE.match(s)
    if m and _clean_isbn(m.group(1)):
        isbn_from_prefix = _clean_isbn(m.group(1))
        s = m.group(2).strip()

    # Anna's Archive: "Title -- Author -- [year/place --] [Publisher --] [ISBN --] <32-hex> -- Anna's Archive"
    if _ANNA_SUFFIX_RE.search(s):
        s2 = _ANNA_SUFFIX_RE.sub("", s).strip()
        parts = [p.strip() for p in s2.split(" -- ") if p.strip()]
        if parts and _HEX32_RE.match(parts[-1]):
            parts.pop()
        isbn, publisher, year = _pop_trailing_metadata(parts)
        isbn = isbn or isbn_from_prefix
        if len(parts) >= 2:
            return ParsedTitle(title=parts[0], author=parts[1], isbn=isbn, publisher=publisher, year=year, confidence="high")
        if len(parts) == 1:
            return ParsedTitle(title=parts[0], isbn=isbn, publisher=publisher, year=year, confidence="high")

    # libgen.li: "[Series] Author - Title (year, Publisher) - libgen.xx"
    if _LIBGEN_SUFFIX_RE.search(s):
        s2 = _LIBGEN_SUFFIX_RE.sub("", s).strip()
        s2 = _BRACKET_SERIES_RE.sub("", s2).strip()
        year = publisher = None
        pm = _YEAR_PUBLISHER_PAREN_RE.search(s2)
        if pm:
            year, publisher = pm.group(1), pm.group(2).strip()
            s2 = _YEAR_PUBLISHER_PAREN_RE.sub("", s2).strip()
        if " - " in s2:
            author, title = s2.split(" - ", 1)
            return ParsedTitle(title=title.strip(), author=author.strip(), isbn=isbn_from_prefix, publisher=publisher, year=year, confidence="high")
        return ParsedTitle(title=s2, isbn=isbn_from_prefix, publisher=publisher, year=year, confidence="high")

    # Folder-path leakage: "Category/Author/.../Title - Author" (e.g. Calibre-style export paths).
    # A single "/" is common in perfectly real titles ("TCP/IP Illustrated", "Work/Life Balance",
    # a date) — only treat this as a path leak when there are 3+ segments AND the last segment's
    # " - X" tail duplicates an earlier segment, confirming it's really a repeated author, not
    # coincidental punctuation.
    slash_parts = [p.strip() for p in s.split("/") if p.strip()]
    if len(slash_parts) >= 3 and " - " in slash_parts[-1]:
        maybe_title, maybe_author = slash_parts[-1].rsplit(" - ", 1)
        maybe_author = maybe_author.strip()
        if any(p.lower() == maybe_author.lower() for p in slash_parts[:-1]):
            return ParsedTitle(title=maybe_title.strip(), author=maybe_author, isbn=isbn_from_prefix, confidence="medium")

    # Leaked print-production file extension ("Burn-after-writing BAT.indd")
    s = _LEAKED_EXT_RE.sub("", s).strip()

    return ParsedTitle(title=s, isbn=isbn_from_prefix, confidence="medium" if isbn_from_prefix else "low")
