"""Book identification: turn per-method ISBN evidence into a graded candidate. Pure — no DB, no network.

Confidence classes (docs/steering/metadata-standards.md §3):
  certain  >=2 independent methods agree on the ISBN
  probable one strong method (embedded metadata or filename) and nothing contradicts it
  possible weak or contested evidence (text scan alone, methods disagree, ISBN shared by unrelated files); review queue
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

STRONG = ("opf", "pdf_meta", "filename")  # embedded metadata / explicit filename ISBN
PRIORITY = ("opf", "pdf_meta", "filename", "text")
_ISBN_TOKEN = re.compile(r"(?<![0-9A-Za-z])(97[89](?:[\s-]?\d){10}|\d(?:[\s-]?\d){8}[\s-]?[\dXx])(?![0-9A-Za-z])")


@dataclass
class Candidate:
    isbn: str
    method: str
    confidence: str
    alternates: dict[str, str] = field(default_factory=dict)  # method -> conflicting ISBN-13


def _verify_isbn13(isbn: str) -> bool:
    """Check an ISBN-13's check digit. Internal helper used only by `to_isbn13` in this file."""
    try:
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn[:12]))
        return (10 - total % 10) % 10 == int(isbn[12])
    except (ValueError, IndexError):
        return False


def _verify_isbn10(isbn: str) -> bool:
    """Check an ISBN-10's check digit. Internal helper used only by `to_isbn13` in this file."""
    # Duplicated from isbn.py rather than imported: isbn.py imports this module for `decide()`,
    # and these five-line checksum functions aren't worth a shared-module split to avoid the cycle.
    try:
        total = sum(int(ch) * (10 - i) for i, ch in enumerate(isbn[:9]))
        last = 10 if isbn[9] in ("X", "x") else int(isbn[9])
        return (11 - total % 11) % 11 == last
    except (ValueError, IndexError):
        return False


def to_isbn13(raw: str) -> str | None:
    """Checksum-valid ISBN-13 from ISBN-10/13 text; None if it does not validate (never invents a check digit)."""
    d = re.sub(r"[^0-9Xx]", "", raw)
    if len(d) == 13 and d.startswith(("978", "979")) and _verify_isbn13(d):
        return d
    if len(d) == 10 and _verify_isbn10(d):
        core = "978" + d[:9]
        return core + str((10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10)
    return None


def filename_isbn(name: str) -> str | None:
    """ISBN standing alone in a file name (token-bounded, so digits inside hashes/longer numbers never match)."""
    for m in _ISBN_TOKEN.finditer(name):
        if isbn := to_isbn13(m.group(1)):
            return isbn
    return None


def resolve(evidence: dict[str, str]) -> Candidate | None:
    """Choose one ISBN-13 from {method: raw isbn}; grade by agreement."""
    found = {m: i for m, raw in evidence.items() if (i := to_isbn13(raw))}
    if not found:
        return None
    votes: dict[str, list[str]] = defaultdict(list)
    for m, i in found.items():
        votes[i].append(m)
    best = max(votes, key=lambda i: (len(votes[i]), -min(PRIORITY.index(m) for m in votes[i])))
    methods = sorted(votes[best], key=PRIORITY.index)
    alts = {m: i for m, i in found.items() if i != best}
    if len(methods) >= 2 and len(votes) == 1:
        conf = "certain"
    elif len(methods) >= 2:
        conf = "probable"  # majority, but something disagrees
    elif alts:
        conf = "possible"  # single voice against another: contested
    else:
        conf = "probable" if methods[0] in STRONG else "possible"
    return Candidate(best, methods[0], conf, alts)


def norm_title(s: str) -> str:
    """Lowercase, unescape HTML entities, strip accents, collapse punctuation."""
    s = unicodedata.normalize("NFKD", html.unescape(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\W+", " ", s.lower()).strip()


def same_title(a: str, b: str) -> bool:
    """Fuzzy title equality: normalized containment, or a similarity ratio for longer strings.
    Used by `reject_shared` in this file and by `verify` below."""
    a, b = norm_title(a), norm_title(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return min(len(a), len(b)) >= 12 and SequenceMatcher(None, a, b).ratio() >= 0.6  # short titles: containment only


def reject_shared(cands: dict[str, Candidate], titles: dict[str, str]) -> list[str]:
    """Library pass: an ISBN carried by unrelated titles is a placeholder/template value.

    Files whose title matches the ISBN's majority cluster (>=2 files, >= half) keep it; the rest are downgraded to
    'possible'. Returns the downgraded keys. Mutates `cands`.
    """
    by_isbn: dict[str, list[str]] = defaultdict(list)
    for k, c in cands.items():
        by_isbn[c.isbn].append(k)
    downgraded: list[str] = []
    for keys in by_isbn.values():
        if len(keys) < 2:
            continue
        clusters: list[list[str]] = []
        for k in keys:
            for cl in clusters:
                if same_title(titles.get(k, ""), titles.get(cl[0], "")):
                    cl.append(k)
                    break
            else:
                clusters.append([k])
        if len(clusters) == 1:
            continue
        clusters.sort(key=len, reverse=True)
        top = clusters[0]
        keep = top if len(top) >= 2 and len(top) * 2 >= len(keys) and len(top) > len(clusters[1]) else []
        for k in keys:
            if k not in keep:
                cands[k].confidence = "possible"
                downgraded.append(k)
    return downgraded


@dataclass
class Record:
    """What a structured source (Open Library, ...) says an ISBN is."""

    title: str
    authors: list[str] = field(default_factory=list)


def _surnames(names: list[str]) -> set[str]:
    """Extract normalized surnames from a list of author names. Internal helper used only by
    `authors_overlap` in this file."""
    out: set[str] = set()
    for n in names:
        toks = [t for t in norm_title(n.split(",")[0] if "," in n else n).split() if len(t) > 2]
        if "," in n:  # "Last, First": every token before the comma is surname
            out.update(toks)
        elif toks:
            out.add(toks[-1])
    return out


def authors_overlap(a: list[str], b: list[str]) -> bool:
    """True when the two author lists share a surname (accent/case-insensitive)."""
    return bool(_surnames(a) & _surnames(b))


def verify(title: str, authors: list[str], rec: Record | None) -> str:
    """'verified' when the record matches the file on title or author, 'mismatch' when both disagree,
    'unknown' when there is no record or nothing on the file side to compare."""
    if rec is None:
        return "unknown"
    if not title and not authors:
        return "unknown"
    if title and same_title(title, rec.title):
        return "verified"
    if authors and rec.authors and authors_overlap(authors, rec.authors):
        return "verified"
    if (title and rec.title) or (authors and rec.authors):
        return "mismatch"
    return "unknown"


def apply_verification(cand: Candidate, verdict: str) -> None:
    """R4/R12: a source-confirmed ISBN is certain; a contradicted one goes to the review queue."""
    if verdict == "verified":
        cand.confidence = "certain"
    elif verdict == "mismatch":
        cand.confidence = "possible"


@dataclass
class Decision:
    """What extract_and_store_isbn should do with a resolved Candidate. Pure — no DB, no I/O."""

    isbn: str | None
    method: str | None
    confidence: str | None
    write: bool  # R4: only certain/probable get auto-applied; possible is queued, not written


def decide(cheap: dict[str, str], expensive: dict[str, str] | None = None) -> Decision:
    """R3: try cheap evidence (OPF/PDF-meta/filename) first; only fall back to expensive evidence
    (full-text scan, OCR-adjacent) when cheap evidence didn't produce something auto-appliable —
    running a full-text scan on every book regardless of an already-strong hit is wasted work."""
    cand = resolve(cheap)
    if (cand is None or cand.confidence == "possible") and expensive:
        merged = {**cheap, **expensive}
        cand = resolve(merged) or cand
    if cand is None:
        return Decision(None, None, None, write=False)
    return Decision(cand.isbn, cand.method, cand.confidence, write=cand.confidence in ("certain", "probable"))
