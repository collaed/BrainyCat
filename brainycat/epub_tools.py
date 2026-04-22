"""EPUB merge and split operations."""

from __future__ import annotations

import os
import tempfile
from typing import Any
from uuid import UUID

import ebooklib
from ebooklib import epub

from brainycat.db import fetch_one


async def merge_epubs(book_ids: list[str], title: str, author: str = "") -> dict[str, Any]:
    """Merge multiple EPUBs into a single EPUB."""
    merged = epub.EpubBook()
    merged.set_identifier(f"brainycat-merged-{'-'.join(book_ids[:3])}")
    merged.set_title(title)
    merged.set_language("en")
    if author:
        merged.add_author(author)

    spine: list[Any] = ["nav"]
    toc: list[Any] = []
    item_counter = 0

    for bid in book_ids:
        row = await fetch_one(
            "SELECT bf.file_path, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id "
            "WHERE bf.book_id = $1 AND bf.format = 'epub' LIMIT 1",
            UUID(bid),
        )
        if not row:
            continue

        try:
            book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        except Exception:
            continue

        section_items = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            item_counter += 1
            new_name = f"part{item_counter}_{item.get_name()}"
            new_item = epub.EpubHtml(title=item.get_name(), file_name=new_name, lang="en")
            new_item.set_content(item.get_content())
            merged.add_item(new_item)
            spine.append(new_item)
            section_items.append(new_item)

        # Copy images/CSS
        for item in book.get_items():
            if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_STYLE):
                item_counter += 1
                new_name = f"res{item_counter}_{os.path.basename(item.get_name())}"
                new_item = epub.EpubItem(file_name=new_name, media_type=item.media_type, content=item.get_content())
                merged.add_item(new_item)

        if section_items:
            toc.append((epub.Section(row["title"]), section_items))

    merged.toc = toc
    merged.add_item(epub.EpubNcx())
    merged.add_item(epub.EpubNav())
    merged.spine = spine

    out_path = tempfile.mktemp(suffix=".epub", dir="/data/books")
    epub.write_epub(out_path, merged)
    return {"path": out_path, "parts": len(book_ids)}


async def split_epub(book_id: str) -> dict[str, Any]:
    """Split an EPUB at chapter boundaries into separate EPUBs."""
    row = await fetch_one(
        "SELECT bf.file_path, b.title, b.id FROM book_files bf JOIN books b ON b.id = bf.book_id "
        "WHERE bf.book_id = $1 AND bf.format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub"}

    try:
        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
    except Exception as e:
        return {"error": str(e)[:100]}

    docs = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    if len(docs) < 2:
        return {"error": "only 1 chapter, nothing to split"}

    parts = []
    for i, doc in enumerate(docs):
        part = epub.EpubBook()
        part.set_identifier(f"brainycat-split-{book_id}-{i}")
        part.set_title(f"{row['title']} — Part {i + 1}")
        part.set_language("en")

        item = epub.EpubHtml(title=doc.get_name(), file_name=doc.get_name(), lang="en")
        item.set_content(doc.get_content())
        part.add_item(item)
        part.add_item(epub.EpubNcx())
        part.add_item(epub.EpubNav())
        part.spine = ["nav", item]
        part.toc = [epub.Link(doc.get_name(), f"Part {i + 1}", f"part{i}")]

        out = tempfile.mktemp(suffix=".epub", dir="/data/books")
        epub.write_epub(out, part)
        parts.append(out)

    return {"parts": len(parts), "files": parts}
