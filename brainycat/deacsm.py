"""DeACSM — convert Adobe DRM .acsm files to DRM-free EPUB/PDF.

Uses libgourou (open-source ACSM handler) if installed.
NOT included in Docker image — requires manual installation of libgourou-bin.
See: https://indefero.soutade.fr/p/libgourou
Legal: for personal backup of purchased books only.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute


async def convert_acsm(acsm_path: str, book_id: str | None = None) -> dict[str, Any]:
    """Convert an .acsm file to DRM-free EPUB or PDF."""
    if not os.path.isfile(acsm_path):
        return {"error": "file not found"}

    # Check for acsmdownloader (libgourou CLI)
    acsmdownloader = shutil.which("acsmdownloader")
    if not acsmdownloader:
        return {
            "error": "acsmdownloader not installed",
            "hint": "Install libgourou: apt install libgourou-bin or build from https://indefero.soutade.fr/p/libgourou",
        }

    out_dir = tempfile.mkdtemp(prefix="deacsm_")
    try:
        proc = await asyncio.create_subprocess_exec(
            acsmdownloader,
            "-d",
            out_dir,
            "-f",
            acsm_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return {"error": f"acsmdownloader failed: {stderr.decode()[:200]}"}

        # Find the output file
        output_files = [f for f in os.listdir(out_dir) if f.endswith((".epub", ".pdf"))]
        if not output_files:
            return {"error": "no output file produced"}

        out_file = os.path.join(out_dir, output_files[0])
        fmt = "epub" if output_files[0].endswith(".epub") else "pdf"

        # If we have a book_id, register the file
        if book_id:
            dest = f"/data/books/{book_id}.{fmt}"
            shutil.move(out_file, dest)
            await execute(
                "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,$3,$4,$5)",
                uuid4(),
                UUID(book_id),
                fmt,
                dest,
                output_files[0],
            )
            return {"ok": True, "format": fmt, "path": dest}

        return {"ok": True, "format": fmt, "path": out_file}

    finally:
        if book_id:
            shutil.rmtree(out_dir, ignore_errors=True)


def is_acsm(path: str) -> bool:
    """Check if a file is an ACSM file."""
    if path.lower().endswith(".acsm"):
        return True
    try:
        with open(path) as f:
            head = f.read(200)
        return "<fulfillmentToken" in head or "adobe.com" in head
    except Exception:
        return False
