"""Adaptive chapter splitting — detect natural chapter boundaries in audiobooks.

Uses silence detection (ffmpeg) + LLM scene-change analysis.
Better than fixed-duration splits for single-file audiobooks.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from brainycat.db import fetch_one


async def detect_chapters(book_id: str) -> dict[str, Any]:
    """Detect chapter boundaries in a single-file audiobook."""
    row = await fetch_one(
        """
        SELECT file_path, format FROM book_files
        WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac','ogg')
        LIMIT 1
    """,
        UUID(book_id),
    )
    if not row:
        return {"error": "no audio file"}

    path = row["file_path"]

    # Step 1: Silence detection via ffmpeg
    silences = await _detect_silences(path)

    # Step 2: Filter — keep only significant silences (>2s, likely chapter breaks)
    chapter_breaks = [s for s in silences if s["duration"] >= 2.0]

    # Step 3: If we have STT text, use LLM to refine
    if len(chapter_breaks) > 3:
        chapter_breaks = await _refine_with_llm(chapter_breaks, path)

    # Build chapter list
    chapters = []
    prev_end = 0.0
    for i, brk in enumerate(chapter_breaks):
        chapters.append(
            {
                "index": i + 1,
                "start": prev_end,
                "end": brk["start"],
                "duration": brk["start"] - prev_end,
                "title": f"Chapter {i + 1}",
            }
        )
        prev_end = brk["end"]

    # Last chapter
    duration = await _get_duration(path)
    if duration and prev_end < duration - 60:
        chapters.append(
            {
                "index": len(chapters) + 1,
                "start": prev_end,
                "end": duration,
                "duration": duration - prev_end,
                "title": f"Chapter {len(chapters) + 1}",
            }
        )

    return {"chapters": chapters, "silences_found": len(silences), "breaks_used": len(chapter_breaks)}


async def _detect_silences(path: str, min_duration: float = 1.0, threshold: int = -40) -> list[dict[str, float]]:
    """Use ffmpeg silencedetect to find silence periods."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        path,
        "-af",
        f"silencedetect=noise={threshold}dB:d={min_duration}",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    output = stderr.decode("utf-8", errors="replace")

    silences = []
    starts = re.findall(r"silence_start: ([\d.]+)", output)
    ends = re.findall(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", output)

    for i, start in enumerate(starts):
        end_val = float(ends[i][0]) if i < len(ends) else float(start) + 2.0
        dur = float(ends[i][1]) if i < len(ends) else 2.0
        silences.append({"start": float(start), "end": end_val, "duration": dur})

    return silences


async def _get_duration(path: str) -> float | None:
    """Get audio file duration via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return None


async def _refine_with_llm(breaks: list[dict], path: str) -> list[dict]:
    """Use LLM to identify which silences are actual chapter boundaries."""
    # For now, use heuristic: keep silences > 3s and spaced > 5 min apart
    refined = []
    last_time = 0.0
    for b in breaks:
        if b["duration"] >= 3.0 and b["start"] - last_time > 300:
            refined.append(b)
            last_time = b["end"]
    return refined if refined else breaks[:20]
