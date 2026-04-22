"""KFX input — read Amazon KFX format (Ion binary containers).

KFX is Amazon's current Kindle format. It's a SQLite database containing
Ion binary data blobs. We extract:
- Text content (for search, fingerprinting, word count)
- Metadata (title, author, ASIN, language, publisher)
- Cover image

This is a best-effort parser — KFX is undocumented and complex.
For full fidelity, Amazon's Kindle Previewer would be needed.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any


def is_kfx(path: str) -> bool:
    """Check if a file is KFX format."""
    if path.lower().endswith(".kfx"):
        return True
    # KFX can also be a SQLite DB
    try:
        with open(path, "rb") as f:
            magic = f.read(16)
            return magic[:6] == b"SQLite" or magic[:4] == b"\xe0\x01\x00\xea"
    except Exception:
        return False


def extract_kfx_metadata(path: str) -> dict[str, Any]:
    """Extract metadata from a KFX file."""
    result: dict[str, Any] = {"format": "kfx"}

    try:
        # KFX is typically a SQLite database
        conn = sqlite3.connect(path)
        cursor = conn.cursor()

        # Check for KFX tables
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if "fragments" in tables:
            # Standard KFX container
            for row in cursor.execute("SELECT key, value FROM fragments"):
                key, blob = row
                _parse_fragment(key, blob, result)

        elif "metadata" in tables:
            # Alternative KFX layout
            for row in cursor.execute("SELECT key, value FROM metadata"):
                key, value = row
                if key == "title":
                    result["title"] = value
                elif key == "author":
                    result["authors"] = [value]
                elif key == "ASIN":
                    result["asin"] = value
                elif key == "language":
                    result["language"] = value
                elif key == "publisher":
                    result["publisher"] = value

        conn.close()
    except sqlite3.DatabaseError:
        # Not a SQLite KFX — try as raw Ion binary
        _parse_ion_kfx(path, result)

    return result


def extract_kfx_text(path: str) -> str:
    """Extract plain text content from a KFX file."""
    text_parts: list[str] = []

    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if "fragments" in tables:
            for row in cursor.execute("SELECT value FROM fragments"):
                blob = row[0]
                if isinstance(blob, bytes):
                    # Extract readable text from Ion blobs
                    text = _extract_text_from_ion(blob)
                    if text:
                        text_parts.append(text)

        conn.close()
    except sqlite3.DatabaseError:
        # Try reading as binary
        try:
            with open(path, "rb") as f:
                data = f.read()
            text_parts.append(_extract_text_from_ion(data))
        except Exception:
            pass

    return "\n".join(text_parts)


def extract_kfx_cover(path: str) -> bytes | None:
    """Extract cover image from a KFX file."""
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if "fragments" in tables:
            for row in cursor.execute("SELECT value FROM fragments"):
                blob = row[0]
                if isinstance(blob, bytes):
                    # JPEG magic
                    if b"\xff\xd8\xff" in blob:
                        start = blob.index(b"\xff\xd8\xff")
                        # Find JPEG end
                        end = blob.rfind(b"\xff\xd9")
                        if end > start:
                            return blob[start : end + 2]
                    # PNG magic
                    if b"\x89PNG" in blob:
                        start = blob.index(b"\x89PNG")
                        return blob[start:]

        conn.close()
    except Exception:
        pass
    return None


def _parse_fragment(key: Any, blob: bytes, result: dict[str, Any]) -> None:
    """Parse a KFX fragment blob for metadata."""
    if not isinstance(blob, bytes) or len(blob) < 4:
        return

    # Look for readable strings that might be metadata
    strings = re.findall(rb"[\x20-\x7e]{10,}", blob)
    for s in strings:
        text = s.decode("ascii", errors="ignore")
        if "title" in str(key).lower() and not result.get("title"):
            result["title"] = text
        elif "author" in str(key).lower():
            result.setdefault("authors", []).append(text)
        elif "ASIN" in text or "asin" in str(key).lower():
            asin_match = re.search(r"B[A-Z0-9]{9}", text)
            if asin_match:
                result["asin"] = asin_match.group()


def _extract_text_from_ion(blob: bytes) -> str:
    """Extract readable text from an Ion binary blob."""
    # Ion binary uses UTF-8 strings prefixed with length
    # We do a best-effort extraction of readable text runs
    text_parts = []
    i = 0
    while i < len(blob) - 4:
        # Look for UTF-8 text runs (printable ASCII + common Unicode)
        if 0x20 <= blob[i] <= 0x7E or blob[i] >= 0xC0:
            start = i
            while i < len(blob) and (0x20 <= blob[i] <= 0x7E or blob[i] >= 0x80):
                i += 1
            if i - start > 20:  # Only keep substantial text runs
                try:
                    text = blob[start:i].decode("utf-8", errors="ignore").strip()
                    if text and not text.startswith(("<?", "<!", "{")):
                        text_parts.append(text)
                except Exception:
                    pass
        else:
            i += 1

    return " ".join(text_parts)


def _parse_ion_kfx(path: str, result: dict[str, Any]) -> None:
    """Parse a raw Ion binary KFX file."""
    try:
        with open(path, "rb") as f:
            data = f.read(4096)  # Just read header for metadata

        # Look for metadata strings
        strings = re.findall(rb"[\x20-\x7e]{10,}", data)
        for s in strings:
            text = s.decode("ascii", errors="ignore")
            if not result.get("title") and len(text) > 5 and not text.startswith(("http", "<?", "<!")):
                result["title"] = text
                break
    except Exception:
        pass
