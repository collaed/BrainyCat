"""Packt book importer — download your owned/claimed books as EPUB.

Packt serves books as HTML chapters in their online reader.
This module authenticates, extracts chapter content, and assembles an EPUB.
Only downloads books from YOUR account (books you own or claimed via Free Learning).

Configure: BRAINYCAT_PACKT_EMAIL and BRAINYCAT_PACKT_PASSWORD in .env
"""

from __future__ import annotations

import os
import re
from typing import Any

from brainycat.http_client import get_client

PACKT_BASE = "https://www.packtpub.com"
PACKT_API = "https://services.packtpub.com"


async def packt_login(email: str, password: str) -> str | None:
    """Authenticate with Packt and return access token."""
    client = get_client()
    resp = await client.post(
        f"{PACKT_API}/auth-v1/users/tokens",
        json={"username": email, "password": password},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json().get("data", {}).get("access")
    return None


async def packt_list_books(token: str) -> list[dict[str, Any]]:
    """List all books in the user's Packt library."""
    client = get_client()
    books = []
    offset = 0
    while True:
        resp = await client.get(
            f"{PACKT_API}/entitlements-v1/users/me/products?sort=createdAt:DESC&offset={offset}&limit=25",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code != 200:
            break
        data = resp.json().get("data", [])
        if not data:
            break
        for item in data:
            books.append({
                "id": item.get("productId", ""),
                "title": item.get("productName", ""),
                "type": item.get("productType", ""),
            })
        offset += 25
    return books


async def packt_download_book(token: str, product_id: str) -> dict[str, Any]:
    """Download a Packt book's chapters and assemble into EPUB.

    Returns: {ok, title, chapters, epub_path} or {error}
    """
    client = get_client()

    # Get book metadata
    resp = await client.get(
        f"{PACKT_API}/products-v1/products/{product_id}/summary",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return {"error": f"Failed to get book info: {resp.status_code}"}

    book_info = resp.json().get("data", {})
    title = book_info.get("title", "Unknown")
    isbn = book_info.get("isbn13", "")

    # Get table of contents
    resp = await client.get(
        f"{PACKT_API}/products-v1/products/{product_id}/toc",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return {"error": "Failed to get TOC"}

    chapters = resp.json().get("data", [])

    # Download each chapter's HTML content
    chapter_htmls = []
    for ch in chapters:
        ch_id = ch.get("id", "")
        ch_title = ch.get("title", f"Chapter {len(chapter_htmls) + 1}")
        if not ch_id:
            continue

        resp = await client.get(
            f"{PACKT_API}/products-v1/products/{product_id}/chapters/{ch_id}/content",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code == 200:
            content = resp.json().get("data", {}).get("content", "")
            # Strip Packt UI elements, keep book content only
            clean = _strip_packt_chrome(content)
            chapter_htmls.append({"title": ch_title, "html": clean})

        # Be gentle
        import asyncio
        await asyncio.sleep(1)

    if not chapter_htmls:
        return {"error": "No chapters found"}

    # Assemble EPUB
    epub_path = await _assemble_epub(title, isbn, chapter_htmls)

    return {
        "ok": True,
        "title": title,
        "isbn": isbn,
        "chapters": len(chapter_htmls),
        "epub_path": epub_path,
    }


def _strip_packt_chrome(html: str) -> str:
    """Remove Packt website elements, keep book content."""
    # Remove script tags
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    # Remove Packt navigation, headers, footers
    html = re.sub(r'<nav[^>]*>.*?</nav>', "", html, flags=re.DOTALL)
    html = re.sub(r'<header[^>]*>.*?</header>', "", html, flags=re.DOTALL)
    html = re.sub(r'<footer[^>]*>.*?</footer>', "", html, flags=re.DOTALL)
    # Remove Packt-specific classes
    html = re.sub(r'<div[^>]*class="[^"]*(?:sidebar|toolbar|menu|packt)[^"]*"[^>]*>.*?</div>', "", html, flags=re.DOTALL)
    # Remove empty divs
    html = re.sub(r"<div[^>]*>\s*</div>", "", html)
    return html.strip()


async def _assemble_epub(title: str, isbn: str, chapters: list[dict[str, str]]) -> str:
    """Assemble chapter HTMLs into an EPUB file."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(isbn or title)
    book.set_title(title)
    book.set_language("en")

    spine = ["nav"]
    toc = []

    for i, ch in enumerate(chapters):
        chapter = epub.EpubHtml(
            title=ch["title"],
            file_name=f"ch{i:03d}.xhtml",
            content=f"<h1>{ch['title']}</h1>\n{ch['html']}",
        )
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(chapter)

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    import tempfile
    out = tempfile.mktemp(suffix=".epub")
    epub.write_epub(out, book)
    return out


async def import_packt_book(product_id: str, email: str, password: str) -> dict[str, Any]:
    """Full pipeline: login → download → import to BrainyCat library."""
    token = await packt_login(email, password)
    if not token:
        return {"error": "Packt login failed"}

    result = await packt_download_book(token, product_id)
    if not result.get("ok"):
        return result

    # Import into BrainyCat
    from uuid import uuid4

    from brainycat.db import execute
    from brainycat.storage import book_dir

    book_id = uuid4()
    bdir = book_dir(str(book_id))
    os.makedirs(bdir, exist_ok=True)

    import shutil
    filename = f"{result['title'][:80]}.epub"
    dst = os.path.join(bdir, filename)
    shutil.move(result["epub_path"], dst)
    size = os.path.getsize(dst)

    await execute(
        "INSERT INTO books (id, title, isbn, language, created_at, updated_at) "
        "VALUES ($1, $2, $3, 'eng', now(), now())",
        book_id, result["title"], result.get("isbn"),
    )
    await execute(
        "INSERT INTO book_files (book_id, file_path, format, file_size, file_name) "
        "VALUES ($1, $2, 'epub', $3, $4)",
        book_id, dst, size, filename,
    )

    return {
        "ok": True,
        "book_id": str(book_id),
        "title": result["title"],
        "chapters": result["chapters"],
        "size_mb": round(size / 1048576, 1),
    }
