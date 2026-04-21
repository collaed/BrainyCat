"""Piper TTS — ebook to audiobook, one MP3 per chapter."""

from __future__ import annotations

import asyncio
import os
import shutil
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one
from brainycat.jobs import create_job, run_in_background, update_job


async def _tts_available() -> str:
    if shutil.which("piper"):
        return "piper"
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return "espeak"
    return "none"


async def _synthesize(text: str, wav_path: str, voice: str, engine: str) -> bool:
    if engine == "piper":
        model = os.environ.get("PIPER_VOICE", voice)
        if not os.path.isfile(model):
            model = f"/opt/piper-voices/{voice}.onnx"
        if not os.path.isfile(model):
            model = voice
        proc = await asyncio.create_subprocess_exec(
            "piper",
            "--model",
            model,
            "--output_file",
            wav_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=text[:50000].encode())
    else:
        cmd = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
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


async def convert_to_audiobook(book_id: str, voice: str = "en_US-lessac-medium", user_id: str | None = None) -> str:
    job_id = await create_job("tts", book_id=book_id, user_id=user_id, params={"voice": voice})

    async def _run() -> None:
        engine = await _tts_available()
        if engine == "none":
            await update_job(job_id, status="failed", error="No TTS engine")
            return

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
                    title = soup.find(["h1", "h2", "h3"])
                    ch_title = title.get_text(strip=True) if title else item.get_name()
                    chapters.append({"title": ch_title, "text": text})
        except Exception as e:
            await update_job(job_id, status="failed", error=f"EPUB parse: {e}")
            return

        if not chapters:
            await update_job(job_id, status="failed", error="No text content")
            return

        from brainycat.storage import book_dir

        out_dir = book_dir(book_id)

        # Generate one MP3 per chapter, register each as a separate file
        for i, ch in enumerate(chapters):
            await update_job(job_id, progress=(i / len(chapters)) * 95)
            safe_title = "".join(c for c in ch["title"][:40] if c.isalnum() or c in " -_").strip() or f"ch{i + 1}"
            mp3_name = f"{i + 1:02d} - {safe_title}.mp3"
            wav_path = os.path.join(out_dir, f"ch{i:03d}.wav")
            mp3_path = os.path.join(out_dir, mp3_name)

            ok = await _synthesize(ch["text"], wav_path, voice, engine)
            if not ok:
                continue

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

            if os.path.isfile(mp3_path):
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
    engine = await _tts_available()
    if engine == "piper":
        return [
            {"id": "en_US-lessac-medium", "language": "en", "name": "Lessac (US English)"},
            {"id": "fr_FR-siwis-medium", "language": "fr", "name": "Siwis (French)"},
            {"id": "de_DE-thorsten-medium", "language": "de", "name": "Thorsten (German)"},
        ]
    return [{"id": "default", "language": "en", "name": f"Default ({engine})"}]
