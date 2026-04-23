"""Reading Feed — web-to-ebook pipeline (replaces Calibre recipes).

Add RSS/Substack/newsletter URLs → fetch daily → clean HTML → EPUB → library.
Optionally: AI summarize, send to Kindle, taste-based recommendations.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client


async def add_feed(user_id: str, url: str, name: str = "") -> dict[str, Any]:
    """Subscribe to an RSS/Atom feed."""
    fid = uuid4()
    if not name:
        name = url.split("/")[-1] or url
    await execute(
        "INSERT INTO reading_feeds (id, user_id, url, name) VALUES ($1,$2,$3,$4)",
        fid,
        UUID(user_id),
        url,
        name,
    )
    return {"id": str(fid), "name": name, "url": url}


async def list_feeds(user_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT id, url, name, last_fetched FROM reading_feeds WHERE user_id = $1 ORDER BY name",
        UUID(user_id),
    )
    return [dict(r) for r in rows]


async def remove_feed(feed_id: str, user_id: str) -> dict[str, bool]:
    await execute("DELETE FROM reading_feeds WHERE id = $1 AND user_id = $2", UUID(feed_id), UUID(user_id))
    return {"ok": True}


async def fetch_feed(feed_id: str) -> dict[str, Any]:
    """Fetch articles from a feed, clean HTML, create EPUB, add to library."""
    feed = await fetch_one("SELECT * FROM reading_feeds WHERE id = $1", UUID(feed_id))
    if not feed:
        return {"error": "feed not found"}

    try:
        client = get_client()
        resp = await client.get(feed["url"])
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)[:100]}

    # Parse RSS/Atom
    articles = _parse_feed(resp.text)
    if not articles:
        return {"error": "no articles found"}

    # Build EPUB from articles
    from ebooklib import epub

    book = epub.EpubBook()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    book.set_identifier(f"brainycat-feed-{feed_id}-{today}")
    book.set_title(f"{feed['name']} — {today}")
    book.set_language("en")

    spine: list[Any] = ["nav"]
    toc: list[Any] = []

    for i, article in enumerate(articles[:20]):
        clean_html = _clean_article(article.get("content", article.get("summary", "")))
        ch = epub.EpubHtml(
            title=article.get("title", f"Article {i + 1}"),
            file_name=f"article_{i:03d}.xhtml",
            lang="en",
        )
        ch.set_content(
            f"<html><body><h1>{article.get('title', '')}</h1><p><em>{article.get('date', '')}</em></p>{clean_html}</body></html>"
        )
        book.add_item(ch)
        spine.append(ch)
        toc.append(epub.Link(f"article_{i:03d}.xhtml", article["title"], f"art_{i}"))

    # Add default stylesheet
    import pathlib

    css_path = pathlib.Path(__file__).parent.parent / "static" / "epub-styles" / "modern.css"
    if css_path.is_file():
        style = epub.EpubItem(file_name="style/feed.css", media_type="text/css", content=css_path.read_bytes())
        book.add_item(style)
        for ch_item in spine[1:]:
            ch_item.add_item(style)

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    out_path = f"/data/books/feed_{feed_id}_{today}.epub"
    epub.write_epub(out_path, book)

    # Add to library
    book_id = uuid4()
    await execute(
        "INSERT INTO books (id, title, description) VALUES ($1,$2,$3)",
        book_id,
        f"{feed['name']} — {today}",
        f"Feed digest: {len(articles)} articles from {feed['url']}",
    )
    await execute(
        "INSERT INTO book_files (id, book_id, format, file_path, file_name) VALUES ($1,$2,'epub',$3,$4)",
        uuid4(),
        book_id,
        out_path,
        os.path.basename(out_path),
    )
    await execute("UPDATE reading_feeds SET last_fetched = now() WHERE id = $1", UUID(feed_id))

    return {"ok": True, "book_id": str(book_id), "articles": len(articles), "path": out_path}


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS or Atom feed into article list."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}

        # RSS
        for item in root.findall(".//item"):
            articles.append(
                {
                    "title": item.findtext("title", ""),
                    "link": item.findtext("link", ""),
                    "date": item.findtext("pubDate", ""),
                    "summary": item.findtext("description", ""),
                    "content": item.findtext("content:encoded", "", ns) or item.findtext("description", ""),
                }
            )

        # Atom
        if not articles:
            for entry in root.findall(".//atom:entry", ns):
                content_el = entry.find("atom:content", ns)
                articles.append(
                    {
                        "title": entry.findtext("atom:title", "", ns),
                        "link": (entry.find("atom:link", ns) or {}).get("href", ""),
                        "date": entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns),
                        "content": content_el.text if content_el is not None and content_el.text else "",
                    }
                )
    except ET.ParseError:
        pass
    return articles


def _clean_article(html: str) -> str:
    """Strip ads, scripts, navigation from article HTML."""
    if not html:
        return "<p>No content available.</p>"
    # Remove scripts, styles, iframes
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<iframe[^>]*>.*?</iframe>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove common ad/nav classes
    html = re.sub(
        r'<div[^>]*class="[^"]*(?:ad|nav|sidebar|footer|comment|share|social)[^"]*"[^>]*>.*?</div>',
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove empty tags
    return re.sub(r"<(\w+)[^>]*>\s*</\1>", "", html)
