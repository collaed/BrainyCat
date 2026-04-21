"""Translation engine — pluggable backends."""

from __future__ import annotations

import os
from typing import Any, Protocol
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one
from brainycat.jobs import create_job, run_in_background, update_job


class TranslationBackend(Protocol):
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str: ...
    def supported_languages(self) -> list[str]: ...


async def translate_book(book_id: str, target_lang: str, backend_name: str = "argos", user_id: str | None = None) -> str:
    """Start translation job. Returns job ID."""
    job_id = await create_job("translate", book_id=book_id, user_id=user_id, params={"target_lang": target_lang, "backend": backend_name})

    async def _run() -> None:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
        if not file_row:
            await update_job(job_id, status="failed", error="No EPUB file")
            return

        # Load backend
        backend = _get_backend(backend_name)
        if not backend:
            await update_job(job_id, status="failed", error=f"Unknown backend: {backend_name}")
            return

        # Extract paragraphs
        try:
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            book = epub.read_epub(file_row["file_path"], options={"ignore_ncx": True})
            chapters = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
                if paragraphs:
                    chapters.append({"name": item.get_name(), "paragraphs": paragraphs})
        except Exception as e:
            await update_job(job_id, status="failed", error=str(e))
            return

        # Detect source language
        from langdetect import detect

        sample = " ".join(ch["paragraphs"][0] for ch in chapters[:5] if ch["paragraphs"])
        source_lang = detect(sample) if sample else "en"

        # Translate
        translated_chapters = []
        total_paras = sum(len(ch["paragraphs"]) for ch in chapters)
        done = 0
        paragraph_map = []

        for ch in chapters:
            translated_paras = []
            for p in ch["paragraphs"]:
                try:
                    t = await backend.translate(p, source_lang, target_lang)
                except Exception:
                    t = p  # fallback to original
                translated_paras.append(t)
                paragraph_map.append({"original": p[:100], "translated": t[:100]})
                done += 1
                await update_job(job_id, progress=(done / total_paras) * 90)
            translated_chapters.append({"name": ch["name"], "paragraphs": translated_paras})

        # Generate translated EPUB
        new_book = epub.EpubBook()
        new_book.set_identifier(str(uuid4()))
        row = await fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
        new_book.set_title(f"{row['title']} ({target_lang})" if row else f"Translation ({target_lang})")
        new_book.set_language(target_lang)

        spine = ["nav"]
        for i, ch in enumerate(translated_chapters):
            c = epub.EpubHtml(title=ch["name"], file_name=f"ch{i:03d}.xhtml")
            c.content = "".join(f"<p>{p}</p>" for p in ch["paragraphs"])
            new_book.add_item(c)
            spine.append(c)
        new_book.add_item(epub.EpubNcx())
        new_book.add_item(epub.EpubNav())
        new_book.spine = spine

        from brainycat.storage import book_dir

        out_path = os.path.join(book_dir(book_id), f"translation_{target_lang}.epub")
        epub.write_epub(out_path, new_book)

        # Create new book record for translation
        trans_book_id = uuid4()
        await execute(
            "INSERT INTO books (id, title) VALUES ($1, $2)",
            trans_book_id,
            f"{row['title']} ({target_lang})" if row else f"Translation ({target_lang})",
        )
        file_id = uuid4()
        await execute(
            "INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size) VALUES ($1,$2,'epub',$3,$4,$5)",
            file_id,
            trans_book_id,
            out_path,
            os.path.basename(out_path),
            os.path.getsize(out_path),
        )
        # Link and record translation
        await execute(
            "INSERT INTO book_links (book_a_id, book_b_id, link_type) VALUES ($1,$2,'translation') ON CONFLICT DO NOTHING",
            UUID(book_id),
            trans_book_id,
        )
        await execute(
            "INSERT INTO book_translations (source_book_id, target_book_id, source_language, target_language, backend, paragraph_map) VALUES ($1,$2,$3,$4,$5,$6)",
            UUID(book_id),
            trans_book_id,
            source_lang,
            target_lang,
            backend_name,
            paragraph_map,
        )
        await update_job(job_id, progress=100, result={"translated_book_id": str(trans_book_id)})

    await run_in_background(job_id, _run())
    return job_id


def _get_backend(name: str) -> Any:
    """Get translation backend by name."""
    if name == "argos":
        from brainycat.translators.argos import ArgosBackend

        return ArgosBackend()
    if name == "llm":
        from brainycat.translators.llm import LLMBackend

        return LLMBackend()
    return None


async def list_backends() -> list[dict[str, Any]]:
    return [
        {"name": "argos", "label": "Argos Translate (local)", "type": "local"},
        {"name": "deepl", "label": "DeepL API", "type": "cloud"},
        {"name": "google", "label": "Google Translate", "type": "cloud"},
        {"name": "llm", "label": "LLM via Intello", "type": "llm"},
        {"name": "ollama", "label": "Ollama (local LLM)", "type": "llm"},
    ]
