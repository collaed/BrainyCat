"""Re-apply postprocess() to an already-extracted scan CSV (e.g. after an Open Library fix) without
re-running extraction.

    python -m tests.golden.rescore in.csv out.csv --lookup-cache ol_records.json
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from tests.golden.postprocess import postprocess
from tests.golden.scan import FIELDS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_in", type=Path)
    ap.add_argument("csv_out", type=Path)
    ap.add_argument("--lookup-cache", type=Path)
    a = ap.parse_args()
    rows = list(csv.DictReader(a.csv_in.open()))
    postprocess(rows, lookup_cache=a.lookup_cache)
    with a.csv_out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
