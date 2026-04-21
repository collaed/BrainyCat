"""STT — audiobook to ebook. Uses Intello's Groq Whisper, falls back to local faster-whisper."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.jobs import create_job, run_in_background, update_job


async def _stt_via_intello(audio_path: str, language: str = "") -> dict | None:
    """Call Intello STT endpoint. Returns {text, provider} or None."""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            with open(audio_path, "rb") as f:
                data = {"language": language} if language else {}
                resp = await client.post(
                    f"{settings.intello_url}/api/v1/voice/transcribe",
                    files={"file": (os.path.basename(audio_path), f, "audio/mpeg")},
                    data=data,
                )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("text"):
                    return result
    except Exception:
        pass
    return None


async def transcribe_audiobook(book_id: str, model: str = "small", user_id: str | None = None) -> str:
    """Start STT transcription job. Returns job ID."""
    job_id = await create_job("stt", book_id=book_id, user_id=user_id, params={"model": model})

    async def _run() -> None:
        files = await fetch_all(
            "SELECT * FROM book_files WHERE book_id = $1 AND format IN ('mp3','m4b','m4a','flac','ogg','opus') ORDER BY file_name",
            UUID(book_id),
        )
        if not files:
            await update_job(job_id, status="failed", error="No audio files")
            return

        chapters = []
        for fi, f in enumerate(files):
            await update_job(job_id, progress=(fi / len(files)) * 90)

            # Try Intello first (Groq Whisper — fast, free)
            result = await _stt_via_intello(f["file_path"])

            if not result:
                # Local fallback
                try:
                    from faster_whisper import WhisperModel

                    whisper = WhisperModel(model, device="cpu", compute_type="int8")
                    segments, _info = whisper.transcribe(f["file_path"])
                    text = " ".join(seg.text for seg in segments)
                    result = {"text": text, "provider": "local_whisper"}
                except ImportError:
                    result = {"text": "", "provider": "none", "error": "No STT available"}

            if result.get("text"):
                chapters.append({"title": f["file_name"], "text": result["text"]})

        if not chapters:
            await update_job(job_id, status="failed", error="No text transcribed")
            return

        # Generate EPUB
        from ebooklib import epub

        from brainycat.storage import book_dir

        ebook = epub.EpubBook()
        ebook.set_identifier(str(uuid4()))
        row = await fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
        ebook.set_title(f"{row['title']} (Transcription)" if row else "Transcription")
        ebook.set_language("en")

        spine = ["nav"]
        for i, ch in enumerate(chapters):
            c = epub.EpubHtml(title=ch["title"], file_name=f"ch{i:03d}.xhtml")
            paragraphs = ch["text"].split(". ")
            html = "".join(f"<p>{p.strip()}.</p>" for p in paragraphs if p.strip())
            c.content = f"<h1>{ch['title']}</h1>{html}"
            ebook.add_item(c)
            spine.append(c)

        ebook.add_item(epub.EpubNcx())
        ebook.add_item(epub.EpubNav())
        ebook.spine = spine

        out_path = os.path.join(book_dir(book_id), "transcription.epub")
        epub.write_epub(out_path, ebook)

        new_id = uuid4()
        await execute(
            """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size)
               VALUES ($1,$2,'epub',$3,'transcription.epub',$4)""",
            new_id,
            UUID(book_id),
            out_path,
            os.path.getsize(out_path),
        )

    await run_in_background(job_id, _run())
    return job_id
