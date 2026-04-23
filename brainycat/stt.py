"""STT — audiobook to ebook. Uses Intello's Groq Whisper, falls back to local faster-whisper."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client
from brainycat.jobs import create_job, run_in_background, update_job


async def _stt_via_intello(audio_path: str, language: str = "") -> dict | None:
    """Call Intello STT endpoint. Returns {text, provider} or None."""
    try:
        client = get_client()
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
                # Store sync map for text↔audio alignment
                import json as _json

                await execute(
                    """INSERT INTO sync_maps (book_id, text_file_id, audio_file_id, chapter_index, mappings)
                       VALUES ($1, $1, $2, $3, $4::jsonb)
                       ON CONFLICT (book_id, text_file_id, audio_file_id, chapter_index) DO UPDATE SET mappings = $4::jsonb""",
                    UUID(book_id),
                    f["id"],
                    fi,
                    _json.dumps({"text_length": len(result["text"]), "provider": result.get("provider", "unknown")}),
                )

        if not chapters:
            await update_job(job_id, status="failed", error="No text transcribed")
            return

        # Split into chapters by detecting "chapter/chapitre/part/partie" keywords
        if len(chapters) == 1:
            import re

            text = chapters[0]["text"]
            # Split on chapter markers
            parts = re.split(
                r"(?i)(chapter\s+\d+|chapitre\s+\d+|part\s+\d+|partie\s+\d+|section\s+\d+)",
                text,
            )
            if len(parts) > 2:
                chapters = []
                i = 1
                while i < len(parts):
                    title = parts[i].strip()
                    body = parts[i + 1].strip() if i + 1 < len(parts) else ""
                    if body:
                        chapters.append({"title": title, "text": body})
                    i += 2
                if not chapters:
                    chapters = [{"title": "Full Text", "text": text}]

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
