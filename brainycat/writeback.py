"""Metadata writeback — update metadata inside ebook files after enrichment."""

from __future__ import annotations

import os
import zipfile
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def writeback_metadata(book_id: str) -> dict[str, Any]:
    """Write enriched metadata back into the EPUB file's OPF."""
    book = await fetch_one("SELECT * FROM books WHERE id = $1", UUID(book_id))
    if not book:
        return {"ok": False, "error": "not found"}

    file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
    if not file_row or not os.path.isfile(file_row["file_path"]):
        return {"ok": False, "error": "no epub file"}

    # Get authors
    authors = await fetch_all(
        "SELECT a.name FROM authors a JOIN books_authors ba ON ba.author_id = a.id WHERE ba.book_id = $1",
        UUID(book_id),
    )
    author_names = [r["name"] for r in authors]

    # Get languages
    langs = await fetch_all(
        "SELECT l.code FROM languages l JOIN books_languages bl ON bl.language_id = l.id WHERE bl.book_id = $1",
        UUID(book_id),
    )
    lang_codes = [r["code"] for r in langs]

    try:
        path = file_row["file_path"]
        _update_epub_opf(
            path,
            title=book["title"],
            authors=author_names,
            isbn=book["isbn"],
            description=book["description"],
            languages=lang_codes,
        )
        await execute(
            "INSERT INTO enrichment_log (book_id, method, success) VALUES ($1, 'writeback', true)",
            UUID(book_id),
        )
        return {"ok": True, "fields_written": ["title", "authors", "isbn", "description", "languages"]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _update_epub_opf(
    epub_path: str,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
    description: str | None = None,
    languages: list[str] | None = None,
) -> None:
    """Update Dublin Core metadata in an EPUB's content.opf."""
    import re
    import shutil
    import tempfile

    # Work on a copy
    tmp = tempfile.mktemp(suffix=".epub")
    shutil.copy2(epub_path, tmp)

    try:
        with zipfile.ZipFile(tmp, "r") as zin:
            # Find OPF
            opf_path = None
            for name in zin.namelist():
                if name.endswith(".opf"):
                    opf_path = name
                    break
            if not opf_path:
                try:
                    container = zin.read("META-INF/container.xml").decode(errors="replace")
                    m = re.search(r'full-path="([^"]+\.opf)"', container)
                    if m:
                        opf_path = m.group(1)
                except KeyError:
                    pass
            if not opf_path:
                return

            opf_content = zin.read(opf_path).decode(errors="replace")

            # Update fields
            if title:
                opf_content = re.sub(
                    r"<dc:title[^>]*>.*?</dc:title>",
                    f"<dc:title>{_xml_escape(title)}</dc:title>",
                    opf_content,
                    count=1,
                )

            if authors:
                # Remove existing creators, add new ones
                opf_content = re.sub(r"<dc:creator[^>]*>.*?</dc:creator>\s*", "", opf_content)
                creators = "".join(f"<dc:creator>{_xml_escape(a)}</dc:creator>\n" for a in authors)
                opf_content = opf_content.replace("</dc:title>", f"</dc:title>\n{creators}")

            if isbn and "<dc:identifier" in opf_content:
                opf_content = re.sub(
                    r"<dc:identifier[^>]*>.*?</dc:identifier>",
                    f'<dc:identifier id="isbn">{isbn}</dc:identifier>',
                    opf_content,
                    count=1,
                )

            if description:
                if "<dc:description" in opf_content:
                    opf_content = re.sub(
                        r"<dc:description[^>]*>.*?</dc:description>",
                        f"<dc:description>{_xml_escape(description[:500])}</dc:description>",
                        opf_content,
                        count=1,
                        flags=re.DOTALL,
                    )
                else:
                    opf_content = opf_content.replace(
                        "</dc:title>",
                        f"</dc:title>\n<dc:description>{_xml_escape(description[:500])}</dc:description>",
                    )

            if languages:
                opf_content = re.sub(r"<dc:language[^>]*>.*?</dc:language>\s*", "", opf_content)
                lang_tags = "".join(f"<dc:language>{lang}</dc:language>\n" for lang in languages)
                opf_content = opf_content.replace("</dc:title>", f"</dc:title>\n{lang_tags}")

            # Write updated EPUB
            with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if item.filename == opf_path:
                        zout.writestr(item, opf_content)
                    else:
                        zout.writestr(item, zin.read(item.filename))
    finally:
        if os.path.isfile(tmp):
            os.unlink(tmp)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


async def batch_writeback(limit: int = 20) -> dict[str, Any]:
    """Write metadata back into books that have been enriched but not written back."""
    rows = await fetch_all(
        """
        SELECT b.id FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        WHERE b.quality_score >= 50 AND bf.format = 'epub'
        AND b.id NOT IN (SELECT book_id FROM enrichment_log WHERE method = 'writeback' AND success)
        LIMIT $1
    """,
        limit,
    )
    written = 0
    for r in rows:
        result = await writeback_metadata(str(r["id"]))
        if result.get("ok"):
            written += 1
    return {"written": written, "batch": len(rows)}
