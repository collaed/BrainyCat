"""Export annotations and clippings as Obsidian-compatible Markdown vault."""

from __future__ import annotations

import io
import zipfile

from brainycat import db


async def export_vault(user_id: str) -> bytes:
    """Generate a ZIP file containing Markdown notes for each book."""
    books = await db.fetch_all(
        """SELECT DISTINCT b.id, b.title, a.name as author
           FROM annotations ann
           JOIN books b ON b.id = ann.book_id
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE ann.user_id = $1
           UNION
           SELECT DISTINCT b.id, b.title, a.name as author
           FROM clippings c
           JOIN books b ON b.id = c.book_id
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE c.user_id = $1""",
        user_id,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for book in books:
            title = (book["title"] or "Untitled").replace("/", "-")
            author = book["author"] or "Unknown"
            md = f"# {title}\n**Author:** {author}\n\n---\n\n## Highlights\n\n"

            # Get annotations
            anns = await db.fetch_all(
                "SELECT text, note, created_at FROM annotations WHERE book_id = $1 AND user_id = $2 ORDER BY created_at",
                book["id"],
                user_id,
            )
            for a in anns:
                md += f"> {a['text']}\n"
                if a["note"]:
                    md += f"\n*{a['note']}*\n"
                md += "\n"

            # Get clippings
            clips = await db.fetch_all(
                "SELECT text, clip_type, created_at FROM clippings WHERE book_id = $1 AND user_id = $2 ORDER BY created_at",
                book["id"],
                user_id,
            )
            if clips:
                md += "## Clippings\n\n"
                for c in clips:
                    prefix = "📝" if c["clip_type"] == "note" else "💡"
                    md += f"- {prefix} {c['text']}\n"

            md += "\n---\n*Exported from BrainyCat*\n"
            zf.writestr(f"BrainyCat/{title}.md", md)

    return buf.getvalue()
