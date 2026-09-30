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
_LIBGEN_SUFFIX_RE = re.compile(r"\s*-\s*libgen\.\w+(-\d+)?\s*$", re.IGNORECASE)  # "-N" collision suffix, if the file got renamed on disk
_YEAR_PUBLISHER_PAREN_RE = re.compile(r"\((\d{4}),\s*([^)]+)\)\s*$")
_LEADING_ISBN_RE = re.compile(r"^(97[89][\d\-]{9,15}|\d{9}[\dXx])\s+(.+)$")
_LEAKED_EXT_RE = re.compile(r"\s+\S{1,6}\.(indd|qxd|docx?|BAT|ai|psd)\s*$", re.IGNORECASE)
_BRACKET_SERIES_RE = re.compile(r"^\[[^\]]+\]\s*")
_PLACE_RE = re.compile(r"^[A-ZÀ-Ý][\w'\-]*(,\s*[A-ZÀ-Ý][\w'\-]*)+$")
_ISBN_SHAPE_RE = re.compile(r"^[\d\-\sXx]{9,17}$")
_BULLET_ISBN_RE = re.compile(r"[·•]\s*ISBN\s*[:.]?\s*([\dXx\-]{9,17})", re.IGNORECASE)
_SITE_SUFFIX_RE = re.compile(r"\s*-\s*[\w.]+\.(com|li|net|org|se|is|io|me)\s*$", re.IGNORECASE)
# Common words that show up in a descriptive subtitle but essentially never in a person's name —
# used to tell "Title - Author" from "Title - Subtitle" when nothing else disambiguates them.
_SUBTITLE_STOPWORDS = {
    "the", "a", "an", "of", "in", "to", "for", "and", "or", "with", "from", "your", "how", "why",
    "what", "guide", "manual", "book", "complete", "essential", "ultimate", "introduction", "edition",
    "des", "les", "la", "le", "du", "de", "et", "pour", "sur", "dans", "un", "une", "au", "aux",
    # Ebook-site names that are just as capitalized-2-words-shaped as a real name — "PDF Room" is
    # the site, not the author. Reject these specifically rather than trying to keep growing this
    # list; a real match will fall back to "title unchanged", which is always the safe default.
    "pdf", "room", "drive", "archive", "library", "download", "books", "ebook", "ebooks", "online", "free",
}


def _looks_like_person_name(s: str) -> bool:
    """Heuristic check that a short string looks like a person's name (short, capitalized words,
    no subtitle-ish stopwords) — internal helper used only by `parse_title` in this file."""
    s = s.strip()
    if not s or len(s) > 40:
        return False
    words = s.split()
    if not (1 <= len(words) <= 4):
        return False
    if any(w.strip(".,").lower() in _SUBTITLE_STOPWORDS for w in words):
        return False
    return all(w[0].isupper() for w in words if w and w[0].isalpha())


@dataclass
class ParsedTitle:
    title: str
    author: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    year: str | None = None
    confidence: str = "low"  # "high": a known structured pattern matched. "medium"/"low": best-effort noise strip.


def _looks_like_year_or_place(s: str) -> bool:
    """Heuristic check that a trailing segment is a publication year or a place name rather than a
    publisher — internal helper used only by `_pop_trailing_metadata` in this file."""
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
    had_hex_prefix = bool(_HEX8_PREFIX_RE.match(s))
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

    # Bullet-ISBN metadata block — a different export tool's format, ISBN on its own bullet line,
    # with either:
    #   "Title - Author\n\n\u00b7 ISBN 123..."               (author joined to the title line), or
    #   "Title - site.com\n\nAuthor \u00b7 ISBN 123..."       (author on its own line just above the bullet)
    # The bullet-ISBN line is a strong, distinctive signal this is a structured record, which is
    # what makes splitting on " - " safe here (unlike a bare title string, where " - " is just as
    # likely to be a real subtitle separator).
    bullet_m = _BULLET_ISBN_RE.search(s)
    if bullet_m:
        bullet_isbn = _clean_isbn(re.sub(r"[^0-9Xx]", "", bullet_m.group(1)))
        isbn = bullet_isbn or isbn_from_prefix
        before = s[: bullet_m.start()]
        lines = [ln.strip(" \t·•") for ln in before.split("\n") if ln.strip(" \t·•")]

        author = None
        title_text = ""
        if len(lines) >= 2:
            # The line right above the bullet is the author; everything before that is the title.
            author = lines[-1]
            title_text = " ".join(lines[:-1])
        elif lines:
            title_text = lines[0]

        title_text = _SITE_SUFFIX_RE.sub("", title_text).strip()
        title_text = re.sub(r"\\([()\[\].,;:!?])", r"\1", title_text)  # un-escape "\(...\)" leakage

        if not author and " - " in title_text:
            maybe_title, maybe_author = title_text.rsplit(" - ", 1)
            title_text, author = maybe_title.strip(), maybe_author.strip()

        return ParsedTitle(title=title_text, author=author, isbn=isbn, confidence="high" if (isbn or author) else "medium")

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

    # Bare "hex8 Title - Author" with no other marker at all. The content-hash prefix alone is
    # already a strong signal this is a filename-derived title (real book titles don't start with
    # 8 lowercase hex chars) — but a single " - " is still ambiguous (could be a real subtitle), so
    # only split it when the text after the last " - " is shaped like a short person's name and not
    # a descriptive phrase ("Matthew MacDonald" yes; "Tackling Complexity in the Heart of Software" no).
    if had_hex_prefix and " - " in s:
        maybe_title, maybe_author = s.rsplit(" - ", 1)
        if _looks_like_person_name(maybe_author):
            return ParsedTitle(title=maybe_title.strip(), author=maybe_author.strip(), isbn=isbn_from_prefix, confidence="medium")

    return ParsedTitle(title=s, isbn=isbn_from_prefix, confidence="medium" if isbn_from_prefix else "low")
