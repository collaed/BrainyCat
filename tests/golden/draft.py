"""Draft a golden manifest for a directory of real files. Output is a DRAFT for human review, not truth.

Independent evidence only where possible: title/authors from the file name (Anna's Archive / libgen patterns),
OPF metadata, and an ISBN accepted only when >=2 methods agree. Everything else is left for the reviewer.

    python -m tests.golden.draft /path/to/corpus > manifest.draft.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from brainycat.isbn import extract_from_filename
from brainycat.title_confidence import parse_annas_archive_filename
from tests.golden.runner import identify_file

_LIBGEN = re.compile(r"^(?P<author>[^()]+?) - (?P<title>.+?) \((?P<rest>[^()]*)\)(?: - libgen\.\w+)?$")


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def from_filename(name: str) -> dict[str, str]:
    stem = re.sub(r"\.\w{2,5}$", "", name)
    d = parse_annas_archive_filename(name)
    if d.get("title"):
        return d
    m = _LIBGEN.match(stem)
    return {"title": m["title"].strip(), "author": m["author"].strip()} if m else {}


def draft(root: Path) -> dict:
    entries = []
    for p in sorted(root.rglob("*.*")):
        if p.suffix.lower() not in {".epub", ".pdf", ".mobi", ".azw3"}:
            continue
        got = identify_file(p)
        fn = from_filename(p.name)
        expect: dict = {}
        if got.get("title") and fn.get("title") and _norm(fn["title"][:20]) in _norm(got["title"]):
            expect["title"] = got["title"]  # OPF and filename agree
        fn_isbn = extract_from_filename(p.name)
        if got.get("isbn") and fn_isbn and got["isbn"] == fn_isbn:
            expect["isbn13"] = got["isbn"]  # two independent methods agree
        entries.append(
            {
                "file": str(p.relative_to(root)),
                "reviewed": False,
                "expect": expect,
                "evidence": {"filename": fn, "found": {k: v for k, v in got.items() if k != "authors"}},
            }
        )
    return {"root": str(root), "entries": entries}


if __name__ == "__main__":
    sys.stdout.write(yaml.safe_dump(draft(Path(sys.argv[1])), allow_unicode=True, sort_keys=False, width=200))
