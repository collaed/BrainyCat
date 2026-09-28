"""Score a scan CSV without ground truth: coverage, method agreement, and Open Library title verification.

    python -m tests.golden.evaluate scan.csv [--verify 400] [--cache ol_cache.json]

'verified' = the ISBN's Open Library record title matches the file's own title (OPF, else filename).
It is a proxy for precision: mismatches are candidates for wrong ISBNs and get listed for review.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

from brainycat.identify import same_title
from tests.golden.runner import _to13


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


title_match = same_title


def ol_title(client: httpx.Client, isbn: str, cache: dict[str, str | None]) -> str | None:
    if isbn in cache:
        return cache[isbn]
    title = None
    for _ in range(2):
        try:
            r = client.get(f"https://openlibrary.org/isbn/{isbn}.json", follow_redirects=True, timeout=20)
            if r.status_code == 200:
                title = r.json().get("title")
            break
        except httpx.HTTPError:
            time.sleep(1)
    cache[isbn] = title
    time.sleep(0.25)
    return title


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--verify", type=int, default=400)
    ap.add_argument("--cache", type=Path, default=Path("ol_cache.json"))
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    rows = list(csv.DictReader(a.csv.open()))
    n = len(rows)
    out = [f"files={n}"]
    by_fmt = Counter(r["format"] for r in rows)
    got = [r for r in rows if r["isbn"]]
    out.append(f"isbn_coverage={len(got)}/{n} ({len(got) / n:.1%})  by_method={dict(Counter(r['method'] for r in got))}")
    for f in by_fmt:
        k = sum(1 for r in rows if r["format"] == f and r["isbn"])
        out.append(f"  {f}: {k}/{by_fmt[f]} ({k / by_fmt[f]:.1%})")
    if "lookup" in rows[0]:
        out.append(f"lookup_verdicts={dict(Counter(r['lookup'] for r in got))}  by_class={dict(Counter(r['confidence'] for r in got))}")
    out.append(f"titles_available={sum(1 for r in rows if r['title'] or r['fn_title'])}/{n}  errors={sum(1 for r in rows if r['error'])}")

    multi = [
        r for r in rows if len({_to13(v.split("=")[1]) for v in r["all_isbns"].split(";") if v}) >= 1 and r["all_isbns"].count("=") >= 2
    ]
    agree = sum(1 for r in multi if len({_to13(v.split("=")[1]) for v in r["all_isbns"].split(";")}) == 1)
    out.append(f"method_agreement={agree}/{len(multi)} files with >=2 methods agree" if multi else "method_agreement=n/a")

    cache: dict[str, str | None] = json.loads(a.cache.read_text()) if a.cache.exists() else {}
    groups = {
        "auto": [r for r in got if r.get("confidence", "certain") in ("certain", "probable")],
        "queue": [r for r in got if r.get("confidence") == "possible"],
    }
    out.append(f"auto_apply={len(groups['auto'])}/{n} ({len(groups['auto']) / n:.1%})  queue={len(groups['queue'])}")
    bad: list[str] = []
    with httpx.Client(headers={"User-Agent": "brainycat-golden/0.1"}) as c:
        for name, grp in groups.items():
            cands = [r for r in grp if (r["title"] or r["fn_title"])]
            random.Random(7).shuffle(cands)
            verdicts: Counter[str] = Counter()
            for r in cands[: a.verify]:
                t = ol_title(c, _to13(r["isbn"]), cache)
                if t is None:
                    verdicts["unknown"] += 1
                elif title_match(t, r["title"] or "") or title_match(t, r["fn_title"] or ""):
                    verdicts["verified"] += 1
                else:
                    verdicts["mismatch"] += 1
                    if name == "auto":
                        bad.append(f"{r['method']:8} {r['isbn']} OL={t!r} file={(r['title'] or r['fn_title'])!r}")
            known = verdicts["verified"] + verdicts["mismatch"]
            prec = f"{verdicts['verified'] / known:.1%}" if known else "n/a"
            out.append(f"ol_verification[{name}]={dict(verdicts)}  precision_proxy={prec}")
    a.cache.write_text(json.dumps(cache))
    text = "\n".join(out) + "\n" + "\n".join(bad[:40]) + "\n"
    sys.stdout.write(text)
    if a.report:
        a.report.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
