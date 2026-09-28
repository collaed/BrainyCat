"""Run the current identification pipeline over every book file under a directory and write a CSV.

python -m tests.golden.scan /path/to/library out.csv [--workers 8]
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from brainycat.identify import resolve
from tests.golden.draft import from_filename
from tests.golden.postprocess import postprocess
from tests.golden.runner import evidence, evidence_new, identify_file

EXTS = {".epub", ".pdf", ".mobi", ".azw3"}
FIELDS = [
    "file",
    "format",
    "method",
    "isbn",
    "title",
    "authors",
    "language",
    "fn_title",
    "fn_author",
    "fn_isbn",
    "all_isbns",
    "confidence",
    "lookup",
    "error",
]


def _one(path: Path, pipeline: str = "baseline") -> dict[str, str]:
    row = {"file": str(path), "format": path.suffix.lstrip(".").lower()}
    try:
        got = identify_file(path)
        row.update(method=got.get("method", ""), isbn=got.get("isbn", ""), title=got.get("title", ""))
        row.update(authors="; ".join(got.get("authors", [])), language=got.get("language", ""))
        fn = from_filename(path.name)
        row.update(fn_title=fn.get("title", ""), fn_author=fn.get("author", ""))
        ev = evidence_new(path) if pipeline == "new" else evidence(path)
        row.update(fn_isbn=ev.get("filename", ""), all_isbns=";".join(f"{k}={v}" for k, v in ev.items()))
        if pipeline == "new":
            cand = resolve(ev)
            row.update(isbn=cand.isbn if cand else "", method=cand.method if cand else "", confidence=cand.confidence if cand else "")
    except Exception as e:  # keep scanning; the error is part of the result
        row["error"] = f"{type(e).__name__}: {e}"[:120]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--lookup-cache", type=Path, help="verify ISBNs against Open Library (cache file)")
    ap.add_argument("--pipeline", choices=["baseline", "new"], default="baseline")
    args = ap.parse_args()
    files = sorted(p for p in args.root.rglob("*") if p.suffix.lower() in EXTS)
    with ProcessPoolExecutor(args.workers) as pool:
        rows = []
        for i, row in enumerate(pool.map(partial(_one, pipeline=args.pipeline), files, chunksize=4), 1):
            rows.append(row)
            if i % 250 == 0:
                sys.stderr.write(f"{i}/{len(files)}\n")
    if args.pipeline == "new":  # library-wide pass: ISBNs shared by unrelated titles, then source verification
        postprocess(rows, lookup_cache=args.lookup_cache)
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
