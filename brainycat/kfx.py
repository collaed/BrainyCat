"""KFX input — Amazon's Kindle format.

KFX uses Ion binary serialization inside a SQLite container. Full parsing
requires jhowell's KFX Input plugin (Ion deserialization, DRM detection,
container parsing). We don't reimplement that.

Strategy:
1. If ebook-convert is available (Calibre in Docker): convert KFX→EPUB, extract from EPUB
2. If not: extract what we can from the SQLite container (metadata, cover)
3. For text extraction: convert first, then extract

This is honest: KFX is a complex proprietary format. We use Calibre's
ebook-convert for the heavy lifting, same as everyone else.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Any


def is_kfx(path: str) -> bool:
    """Check if a file is KFX format."""
    if path.lower().endswith(".kfx"):
        return True
    try:
        with open(path, "rb") as f:
            magic = f.read(16)
            return magic[:6] == b"SQLite"
    except Exception:
        return False


async def extract_kfx_metadata(path: str) -> dict[str, Any]:
    """Extract metadata from KFX. Uses ebook-convert if available."""
    result: dict[str, Any] = {"format": "kfx"}

    if not os.path.isfile(path):
        return result

    # Best path: convert to EPUB via ebook-convert, extract from that
    if shutil.which("ebook-convert"):
        tmp = tempfile.mktemp(suffix=".epub")
        try:
            proc = await asyncio.create_subprocess_exec(
                "ebook-convert",
                path,
                tmp,
                "--no-default-epub-cover",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if os.path.isfile(tmp):
                from brainycat.extract import _extract_epub

                result = _extract_epub(tmp)
                result["format"] = "kfx"
                result["converted_from"] = "kfx"
        except Exception:
            pass
        finally:
            if os.path.isfile(tmp):
                os.unlink(tmp)
        return result

    # Fallback: try to read SQLite metadata directly (limited)
    try:
        import sqlite3

        conn = sqlite3.connect(path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "metadata" in tables:
            for row in conn.execute("SELECT key, value FROM metadata"):
                if row[0] == "title":
                    result["title"] = row[1]
                elif row[0] == "author":
                    result["authors"] = [row[1]]
        conn.close()
    except Exception:
        pass

    return result


def extract_kfx_text(path: str) -> str:
    """Extract text from KFX — requires ebook-convert."""
    if not shutil.which("ebook-convert"):
        return ""
    # Synchronous fallback — convert to txt
    import subprocess

    tmp = tempfile.mktemp(suffix=".txt")
    try:
        subprocess.run(["ebook-convert", path, tmp], capture_output=True, timeout=60)
        if os.path.isfile(tmp):
            with open(tmp) as f:
                return f.read()
    except Exception:
        pass
    finally:
        if os.path.isfile(tmp):
            os.unlink(tmp)
    return ""
