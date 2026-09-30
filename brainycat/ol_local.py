"""Local Open Library lookup — queries a pre-built sqlite index of the OL editions dump instead
of the network. Used by fast_local.py (ISBN/title bulk enrichment) and ol_works.py (work
descriptions) for ~1000 books/min throughput with zero API calls.

The index is built offline by /root/ol_dump/import_ol_dump.py (on the fides host, not part of
this package — it streams OpenLibrary's ol_dump_editions_latest.txt.gz and writes the sqlite file
to /mnt/buffer/brainycat/data/ol_local.sqlite on the host, which is the same bind-mounted volume
the container sees as /data — so it shows up here at /data/ol_local.sqlite (BRAINYCAT_OL_LOCAL_DB)
with no image rebuild needed. Until that file exists, every lookup here returns None and callers
degrade gracefully (see fast_local.py's `conn is None` guard).

BnF (Bibliothèque nationale de France) lookups are NOT covered by the OL dump — its French-language
coverage is thin — so lookup_bnf()/lookup_bnf_title() are permanently no-ops, not "not built yet".
A real BnF source would need its own separate dataset/API.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from typing import Any

DB_PATH = os.environ.get("BRAINYCAT_OL_LOCAL_DB", "/data/ol_local.sqlite")

_conn_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_WORD_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Must match the normalization import_ol_dump.py used when building title_lookup."""
    t = _WORD_RE.sub(" ", title.lower())
    return _WS_RE.sub(" ", t).strip()


def _get_conn() -> sqlite3.Connection | None:
    """Lazily open the sqlite index. Returns None if it hasn't been built yet."""
    global _conn
    if _conn is not None:
        return _conn
    with _conn_lock:
        if _conn is not None:
            return _conn
        if not os.path.isfile(DB_PATH):
            return None
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _conn = conn
        return _conn


def lookup_isbn(isbn: str) -> dict[str, Any] | None:
    """Exact ISBN match against the local index."""
    conn = _get_conn()
    if conn is None:
        return None
    row = conn.execute("SELECT * FROM isbn_lookup WHERE isbn = ?", (isbn,)).fetchone()
    if not row:
        return None
    return {
        "ol_key": row["ol_key"],
        "work_key": row["work_key"],
        "title": row["title"],
        "publisher": row["publisher"],
        "year": row["year"],
        "cover_id": row["cover_id"],
        "subjects": json.loads(row["subjects"]) if row["subjects"] else None,
    }


def lookup_bnf(isbn: str) -> dict[str, Any] | None:
    """BnF has no local dataset — see module docstring. Always None."""
    return None


def lookup_bnf_title(title: str) -> dict[str, Any] | None:
    """BnF has no local dataset — see module docstring. Always None."""
    return None
