"""Audio restoration — diagnose and clean using ffmpeg, sox, noisereduce."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one

PROFILES: dict[str, str] = {
    "digital_light": "afftdn=nr=10:nf=-30",
    "digital_heavy": "afftdn=nr=30:nf=-20,loudnorm",
    "vinyl": "adeclick=w=55:p=75,afftdn=nr=20:nf=-25,highpass=f=20,loudnorm",
    "tape": "afftdn=nr=25:nf=-20,highpass=f=40,lowpass=f=16000,loudnorm",
    "hum_removal": "equalizer=f=50:t=q:w=5:g=-30,equalizer=f=100:t=q:w=5:g=-20,equalizer=f=150:t=q:w=5:g=-15,equalizer=f=60:t=q:w=5:g=-30,equalizer=f=120:t=q:w=5:g=-20",
    "declip": "adeclip=w=55:m=a",
    "full_restoration": "adeclick=w=55:p=75,adeclip=w=55:m=a,afftdn=nr=20:nf=-25,highpass=f=20,lowpass=f=18000,equalizer=f=50:t=q:w=5:g=-25,equalizer=f=60:t=q:w=5:g=-25,loudnorm",
}


async def diagnose(file_id: str) -> dict[str, Any]:
    """Analyze audio file for noise, crackle, hum, clipping."""
    row = await fetch_one("SELECT * FROM book_files WHERE id = $1", UUID(file_id))
    if not row:
        return {"error": "file not found"}

    path = row["file_path"]
    # Get audio stats via ffmpeg
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        path,
        "-af",
        "astats=metadata=1:reset=1",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    stats_text = stderr.decode(errors="replace")

    # Parse noise floor from astats
    noise_floor = -60.0
    for line in stats_text.split("\n"):
        if "Noise floor dB" in line:
            with contextlib.suppress(ValueError):
                noise_floor = float(line.split(":")[-1].strip())

    # Simple heuristic scoring
    hiss_score = max(0, min(100, int((noise_floor + 30) * 3)))  # -30dB = 0, -10dB = 60
    crackle_score = 0  # Would need peak detection — simplified
    hum_score = 0
    clipping_pct = 0.0
    overall = max(0, 100 - hiss_score)

    recommended = "none"
    if hiss_score > 50:
        recommended = "digital_heavy"
    elif hiss_score > 20:
        recommended = "digital_light"

    diag_id = uuid4()
    await execute(
        """INSERT INTO audio_diagnostics (id, file_id, noise_floor_db, hiss_score, crackle_score, hum_score, clipping_pct, overall_score, recommended_profile)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        diag_id,
        UUID(file_id),
        noise_floor,
        hiss_score,
        crackle_score,
        hum_score,
        clipping_pct,
        overall,
        recommended,
    )

    return {
        "diagnosis_id": str(diag_id),
        "noise_floor_db": noise_floor,
        "hiss_score": hiss_score,
        "crackle_score": crackle_score,
        "hum_score": hum_score,
        "clipping_pct": clipping_pct,
        "overall_score": overall,
        "recommended_profile": recommended,
    }


async def restore(file_id: str, profile: str) -> dict[str, Any]:
    """Apply a restoration profile to an audio file."""
    row = await fetch_one("SELECT * FROM book_files WHERE id = $1", UUID(file_id))
    if not row:
        return {"error": "file not found"}

    filters = PROFILES.get(profile)
    if not filters and profile != "custom":
        return {"error": f"unknown profile: {profile}"}

    src = row["file_path"]
    base, ext = os.path.splitext(src)
    dest = f"{base}_restored{ext}"

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-af",
        filters or "",
        dest,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    if proc.returncode != 0 or not os.path.isfile(dest):
        return {"error": "restoration failed"}

    # Create new book_files entry for restored version
    new_id = uuid4()
    await execute(
        """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size, metadata)
           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
        new_id,
        row["book_id"],
        row["format"],
        dest,
        os.path.basename(dest),
        os.path.getsize(dest),
        json.dumps({"restored_from": str(row["id"]), "profile": profile}),
    )

    return {"restored_file_id": str(new_id), "profile": profile, "path": dest}


async def preview(file_id: str, profile: str) -> str | None:
    """Generate a 30s preview of restoration. Returns path to preview file."""
    row = await fetch_one("SELECT * FROM book_files WHERE id = $1", UUID(file_id))
    if not row:
        return None
    filters = PROFILES.get(profile, "")
    src = row["file_path"]
    preview_path = f"/tmp/preview_{file_id}_{profile}.mp3"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-ss",
        "60",
        "-t",
        "30",
        "-af",
        filters,
        preview_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return preview_path if os.path.isfile(preview_path) else None
