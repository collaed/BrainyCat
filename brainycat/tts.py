"""TTS — ebook to audiobook. Uses Intello's Piper TTS, falls back to local espeak."""

from __future__ import annotations

import asyncio
import os
import shutil
from uuid import UUID, uuid4

import httpx

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.jobs import create_job, run_in_background, update_job


async def _tts_via_intello(text: str, language: str = "en") -> bytes | None:
    """Call Intello TTS endpoint. Returns WAV bytes or None."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.intello_url}/api/v1/voice/tts",
                data={"text": text[:50000], "language": language},
            )
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("audio/"):
                return resp.content
    except Exception:
        pass
    return None


async def _tts_local(text: str, wav_path: str) -> bool:
    """Local fallback: espeak-ng."""
    cmd = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
    if not shutil.which(cmd):
        return False
    proc = await asyncio.create_subprocess_exec(
        cmd,
        "-w",
        wav_path,
        "-s",
        "160",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate(input=text[:50000].encode())
    return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0


async def _synthesize_chapter(text: str, mp3_path: str, language: str) -> bool:
    """Synthesize text to MP3 via Intello or local fallback."""
    wav_path = mp3_path.replace(".mp3", ".wav")

    # Try Intello first
    wav_data = await _tts_via_intello(text, language)
    if wav_data:
        with open(wav_path, "wb") as f:
            f.write(wav_data)
    else:
        # Local fallback
        if not await _tts_local(text, wav_path):
            return False

    if not os.path.isfile(wav_path):
        return False

    # WAV → MP3
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        wav_path,
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "128k",
        mp3_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if os.path.isfile(wav_path):
        os.unlink(wav_path)
    return os.path.isfile(mp3_path)


async def convert_to_audiobook(book_id: str, voice: str = "en", user_id: str | None = None) -> str:
    """Start TTS conversion job. Returns job ID."""
    job_id = await create_job("tts", book_id=book_id, user_id=user_id, params={"voice": voice})

    async def _run() -> None:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
        if not file_row:
            await update_job(job_id, status="failed", error="No EPUB file")
            return

        try:
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            ebook = epub.read_epub(file_row["file_path"], options={"ignore_ncx": True})
            chapters = []
            for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                if len(text) > 50:
                    heading = soup.find(["h1", "h2", "h3"])
                    ch_title = heading.get_text(strip=True) if heading else item.get_name()
                    chapters.append({"title": ch_title, "text": text})
        except Exception as e:
            await update_job(job_id, status="failed", error=f"EPUB parse: {e}")
            return

        if not chapters:
            await update_job(job_id, status="failed", error="No text content")
            return

        from brainycat.storage import book_dir

        out_dir = book_dir(book_id)
        language = voice if len(voice) == 2 else "en"

        for i, ch in enumerate(chapters):
            await update_job(job_id, progress=(i / len(chapters)) * 95)
            safe_title = "".join(c for c in ch["title"][:40] if c.isalnum() or c in " -_").strip() or f"ch{i + 1}"
            mp3_name = f"{i + 1:02d} - {safe_title}.mp3"
            mp3_path = os.path.join(out_dir, mp3_name)

            ok = await _synthesize_chapter(ch["text"], mp3_path, language)
            if ok:
                # Store sync map: chapter index → file, for text↔audio sync
                import json as _json

                await execute(
                    """INSERT INTO sync_maps (book_id, text_file_id, audio_file_id, chapter_index, mappings)
                       VALUES ($1, $1, $1, $2, $3::jsonb)
                       ON CONFLICT (book_id, text_file_id, audio_file_id, chapter_index) DO UPDATE SET mappings = $3::jsonb""",
                    UUID(book_id),
                    i,
                    _json.dumps({"chapter_title": ch["title"], "text_length": len(ch["text"]), "mp3_file": mp3_name}),
                )
                fid = uuid4()
                await execute(
                    """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size, mime_type, metadata)
                       VALUES ($1,$2,'mp3',$3,$4,$5,'audio/mpeg',$6::jsonb)""",
                    fid,
                    UUID(book_id),
                    mp3_path,
                    mp3_name,
                    os.path.getsize(mp3_path),
                    f'{{"chapter_index": {i}, "chapter_title": "{ch["title"][:80]}"}}',
                )

    await run_in_background(job_id, _run())
    return job_id


async def list_voices() -> list[dict[str, str]]:
    """List available voices from Intello or local."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.intello_url}/api/v1/voice/status")
            if resp.status_code == 200:
                data = resp.json()
                voices = data.get("voices", [])
                if voices:
                    return [{"id": v.get("language", v["id"])[:2], "language": v.get("language", "")[:2], "name": v["id"]} for v in voices]
    except Exception:
        pass
    return [{"id": "en", "language": "en", "name": "Default (local espeak)"}]
