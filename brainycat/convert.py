"""Format conversion (WeasyPrint) and Kindle delivery (SMTP)."""

from __future__ import annotations

import os
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import aiosmtplib

from brainycat.config import settings
from brainycat.db import execute, fetch_one


async def convert_format(book_id: str, target_format: str) -> dict[str, Any]:
    """Convert EPUB to PDF via WeasyPrint. Other conversions not yet supported."""
    if target_format != "pdf":
        return {"error": f"Conversion to {target_format} not supported yet (only epub→pdf)"}

    row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
    if not row:
        return {"error": "No EPUB source file"}

    try:
        import ebooklib
        import weasyprint
        from ebooklib import epub

        ebook = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        html_parts = [item.get_content().decode(errors="replace") for item in ebook.get_items_of_type(ebooklib.ITEM_DOCUMENT)]
        css = "body{font-family:serif;font-size:11pt;line-height:1.6;margin:2cm}h1,h2,h3{page-break-before:always}img{max-width:100%;height:auto}"
        joiner = "\n"
        full_html = f"<html><head><style>{css}</style></head><body>{joiner.join(html_parts)}</body></html>"
        pdf_bytes = weasyprint.HTML(string=full_html).write_pdf()

        dest = os.path.splitext(row["file_path"])[0] + ".pdf"
        with open(dest, "wb") as f:
            f.write(pdf_bytes)

        new_id = uuid4()
        await execute(
            """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size, mime_type)
               VALUES ($1,$2,'pdf',$3,$4,$5,'application/pdf')""",
            new_id,
            UUID(book_id),
            dest,
            os.path.basename(dest),
            os.path.getsize(dest),
        )
        return {"file_id": str(new_id), "format": "pdf", "size": os.path.getsize(dest)}
    except Exception as e:
        return {"error": f"Conversion failed: {e}"}


async def send_to_kindle(book_id: str, user_id: str) -> dict[str, Any]:
    """Send a book to Kindle via email."""
    user = await fetch_one("SELECT * FROM users WHERE id = $1", UUID(user_id))
    if not user or not user["kindle_email"]:
        return {"error": "No Kindle email configured"}

    # Check if workbook — send PDF instead of EPUB
    book = await fetch_one("SELECT title, is_workbook FROM books WHERE id = $1", UUID(book_id))
    title = book["title"] if book else "Book"
    is_workbook = book["is_workbook"] if book else False

    if is_workbook:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'pdf' LIMIT 1", UUID(book_id))
    else:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))

    if not file_row:
        file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 LIMIT 1", UUID(book_id))
    if not file_row:
        return {"error": "No file available"}

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = "brainycat@ecb.pm"
    msg["To"] = user["kindle_email"]
    msg.set_content(f"Sent from BrainyCat: {title}")

    mime = "application/epub+zip" if file_row["format"] == "epub" else "application/pdf"
    with open(file_row["file_path"], "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype=mime.split("/")[1], filename=file_row["file_name"])

    await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port, use_tls=False)
    return {"ok": True, "sent_to": user["kindle_email"], "format": file_row["format"]}


async def send_to_device(book_id: str, email: str) -> dict[str, Any]:
    """Send a book to any email address."""
    file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
    if not file_row:
        return {"error": "No EPUB file"}

    book = await fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
    title = book["title"] if book else "Book"

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = "brainycat@ecb.pm"
    msg["To"] = email
    msg.set_content(f"Sent from BrainyCat: {title}")

    with open(file_row["file_path"], "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="epub+zip", filename=file_row["file_name"])

    await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port, use_tls=False)
    return {"ok": True, "sent_to": email}
