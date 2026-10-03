"""File-content hashing and Anna's Archive MD5 extraction (K6).

Why this exists: BrainyCat *modifies* files after ingest — `epub_fix.fix_epub()` rewrites EPUBs in
place, and `writeback.writeback_metadata()` later rewrites EPUB OPFs / PDFs. A hash of the *stored*
file therefore won't match:
  - the LibGen / Anna's Archive record (which is the MD5 of the ORIGINAL download), or
  - another user's upload of the same original file (breaking cross-user dedup, M8/K6).

So callers hash the ORIGINAL bytes at ingest, *before* any modification, and store them immutably in
`book_files.original_md5` / `original_sha256`. `anna_md5_from_name()` recovers the download MD5 that
Anna's Archive embeds in filenames (`… -- <32 hex> -- Anna's Archive.epub`) — 1,122 / 3,949 files on
the reference library carry it — before the filename-standardizing rename drops it.

Called by: `watcher._import_file` and `books._ingest_one_file` (at ingest, before `fix_epub`); and by
the offline LibGen/Anna's Archive identification source (`identify_by_md5`), which keys on these MD5s.
"""

from __future__ import annotations

import hashlib
import os
import re

_ANNA_MD5_RE = re.compile(r"(?:^|[^0-9a-f])([0-9a-f]{32})(?:[^0-9a-f]|$)", re.IGNORECASE)


def _hash_file(path: str, algo: str) -> str | None:
    """Stream-hash a file with the named hashlib algorithm; None if unreadable."""
    try:
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def md5_file(path: str) -> str | None:
    """MD5 of a file's bytes (LibGen/Anna's Archive index key). Hash the ORIGINAL, pre-fix bytes."""
    return _hash_file(path, "md5")


def sha256_file(path: str) -> str | None:
    """SHA-256 of a file's bytes. Original-bytes value is the immutable dedup key."""
    return _hash_file(path, "sha256")


def anna_md5_from_name(filename: str) -> str | None:
    """Extract the Anna's Archive download MD5 from a filename, if present.

    Anna's Archive exports look like
    ``21b50b4d Title -- Author -- … -- 1e9c3d90f7395ba6b878c4b76e431e7a -- Anna's Archive.epub``.
    The 32-hex token immediately before the "Anna's Archive" marker is the download MD5. We prefer a
    token adjacent to that marker; if the marker is absent we return the last standalone 32-hex token.
    """
    base = os.path.basename(filename)
    marker = re.search(r"([0-9a-f]{32})\s*--\s*Anna", base, re.IGNORECASE)
    if marker:
        return marker.group(1).lower()
    candidates = _ANNA_MD5_RE.findall(base)
    return candidates[-1].lower() if candidates else None


def capture_original_hashes(path: str, filename: str) -> dict[str, str | None]:
    """Return {original_md5, original_sha256, anna_md5} for a freshly-received file.

    MUST be called before `fix_epub` / any writeback touches the file, so the stored hashes reflect
    the bytes as downloaded (which is what LibGen/AA and other users' uploads will match).
    """
    return {
        "original_md5": md5_file(path),
        "original_sha256": sha256_file(path),
        "anna_md5": anna_md5_from_name(filename),
    }
