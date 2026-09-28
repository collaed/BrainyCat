"""Golden-set harness: run the current file-local identification over a manifest and score it.

Baseline pipeline (offline, no DB, no network) mirrors `isbn.extract_and_store_isbn`:
OPF -> PDF metadata -> filename -> full-text scan. Later stages (source lookups, ladder) plug into `identify_file`.

    python -m tests.golden.runner [--manifest tests/golden/manifest.yaml]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from brainycat.isbn import extract_from_filename, extract_from_opf, extract_from_pdf_metadata, extract_from_text

HERE = Path(__file__).parent


def identify_file(path: Path) -> dict[str, Any]:
    """Return {isbn, title, authors, language, method} for whatever the baseline pipeline finds."""
    out: dict[str, Any] = {}
    fmt = path.suffix.lstrip(".").lower()
    if fmt == "epub":
        opf = extract_from_opf(str(path))
        if opf.get("title"):
            out["title"] = opf["title"]
        if opf.get("author"):
            out["authors"] = [opf["author"]]
        if opf.get("language"):
            out["language"] = opf["language"]
        if opf.get("isbn"):
            out.update(isbn=opf["isbn"], method="opf")
    if not out.get("isbn") and fmt == "pdf":
        isbn = extract_from_pdf_metadata(str(path))
        if isbn:
            out.update(isbn=isbn, method="pdf_meta")
    if not out.get("isbn"):
        isbn = extract_from_filename(path.name)
        if isbn:
            out.update(isbn=isbn, method="filename")
    if not out.get("isbn") and fmt in ("epub", "pdf"):
        from brainycat.fingerprints import _extract_full_text

        data = extract_from_text(_extract_full_text(str(path), fmt) or "")
        isbn = data.get("isbn") or data.get("isbn_10")
        if isbn:
            out.update(isbn=isbn, method="text")
    return out


def evidence(path: Path) -> dict[str, str]:
    """ISBN found by each method independently (for agreement statistics)."""
    out: dict[str, str] = {}
    fmt = path.suffix.lstrip(".").lower()
    if fmt == "epub" and (isbn := extract_from_opf(str(path)).get("isbn")):
        out["opf"] = isbn
    if fmt == "pdf" and (isbn := extract_from_pdf_metadata(str(path))):
        out["pdf_meta"] = isbn
    if isbn := extract_from_filename(path.name):
        out["filename"] = isbn
    if fmt in ("epub", "pdf"):
        from brainycat.fingerprints import _extract_full_text

        data = extract_from_text(_extract_full_text(str(path), fmt) or "")
        if isbn := data.get("isbn") or data.get("isbn_10"):
            out["text"] = isbn
    return out


def evidence_new(path: Path) -> dict[str, str]:
    """Same as `evidence` but with the token-bounded filename extractor."""
    from brainycat.identify import filename_isbn

    ev = evidence(path)
    ev.pop("filename", None)
    if isbn := filename_isbn(path.name):
        ev["filename"] = isbn
    return ev


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


_LANG3 = {"en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita", "pt": "por", "nl": "nld", "ru": "rus", "ja": "jpn", "zh": "zho"}


def _to13(isbn: str) -> str:
    """ISBN-10 -> ISBN-13 for comparison only (canonical storage is task T2)."""
    if len(isbn) != 10:
        return isbn
    core = "978" + isbn[:9]
    return core + str((10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core)) % 10) % 10)


def score(expect: dict[str, Any], got: dict[str, Any]) -> tuple[str, list[str]]:
    """Outcome is 'wrong' if any returned value contradicts expectation, else 'correct' if all expected
    values were found, else 'partial' (some found) or 'none'."""
    if not expect:
        return "unlabeled", []
    wrong: list[str] = []
    hit = miss = 0
    for field, want in expect.items():
        key = "isbn" if field == "isbn13" else field
        have = got.get(key)
        if field == "isbn13":
            have = _to13(have) if have else None
        elif field == "language" and have:
            have = _LANG3.get(str(have).lower()[:2], have) if len(str(have)) == 2 else have  # compare-only; storage standard is T5
        if want is None:
            if have:
                wrong.append(f"{field}: returned {have!r}, none knowable")
            continue
        if not have:
            miss += 1
        elif field == "authors":
            (hit := hit + 1) if {_norm(a) for a in have} == {_norm(a) for a in want} else wrong.append(f"{field}: {have} != {want}")
        elif _norm(str(have)) == _norm(str(want)):
            hit += 1
        else:
            wrong.append(f"{field}: {have!r} != {want!r}")
    if wrong:
        return "wrong", wrong
    if miss == 0:
        return "correct", []
    return ("partial" if hit else "none"), []


def run(manifest: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(manifest.read_text())
    root = Path(os.environ.get("GOLDEN_ROOT") or (manifest.parent / cfg.get("root", ".")))
    rows, skipped = [], []
    for e in cfg["entries"]:
        p = root / e["file"]
        if not p.is_file():
            skipped.append(e["file"])
            continue
        got = identify_file(p)
        outcome, why = score(e["expect"], got)
        rows.append({"file": e["file"], "outcome": outcome, "why": why, "method": got.get("method")})
    counts = {k: sum(r["outcome"] == k for r in rows) for k in ("correct", "partial", "none", "wrong", "unlabeled")}
    answered = counts["correct"] + counts["wrong"]
    labeled = len(rows) - counts["unlabeled"]
    return {
        "rows": rows,
        "skipped": skipped,
        "counts": counts,
        "precision": counts["correct"] / answered if answered else None,
        "rate": counts["correct"] / labeled if labeled else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(HERE / "manifest.yaml"))
    r = run(Path(ap.parse_args().manifest))
    for row in r["rows"]:
        print(f"{row['outcome']:8} {row['file']}  {row['method'] or ''}  {'; '.join(row['why'])}")  # noqa: T201
    if r["skipped"]:
        print(f"skipped (file missing): {len(r['skipped'])}")  # noqa: T201
    p, rate = r["precision"], r["rate"]
    print(f"counts={r['counts']} precision={'n/a' if p is None else f'{p:.1%}'} rate={'n/a' if rate is None else f'{rate:.1%}'}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
