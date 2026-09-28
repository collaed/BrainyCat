"""Format conversion (WeasyPrint) and Kindle delivery (SMTP or Resend)."""

from __future__ import annotations

import base64
import os
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import aiosmtplib

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client


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


def _smtp_from() -> str:
    return settings.smtp_from or settings.smtp_user or f"brainycat@{settings.smtp_host}"


async def _smtp_send(msg: EmailMessage) -> None:
    kwargs: dict[str, Any] = {
        "hostname": settings.smtp_host,
        "port": settings.smtp_port,
        "use_tls": settings.smtp_port == 465,  # implicit TLS; port 587 uses opportunistic STARTTLS by default
    }
    if settings.smtp_user:
        kwargs["username"] = settings.smtp_user
        kwargs["password"] = settings.smtp_password
    await aiosmtplib.send(msg, **kwargs)


async def _resend_send(*, to: str, subject: str, text: str, filename: str, content: bytes) -> dict[str, Any]:
    """Send via the Resend HTTP API. Returns {"id": ...} on success — pass that id to
    check_send_status() to look up delivery/bounce status after the fact."""
    resp = await get_client().post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={
            "from": _smtp_from(),
            "to": [to],
            "subject": subject,
            "text": text,
            "attachments": [{"filename": filename, "content": base64.b64encode(content).decode()}],
        },
    )
    if resp.status_code >= 400:
        return {"error": f"Resend API error {resp.status_code}: {resp.text[:300]}"}
    return resp.json()


async def check_send_status(message_id: str) -> dict[str, Any]:
    """GET /emails/{id} on Resend — reports last_event (e.g. delivered/bounced/complained)."""
    if not settings.resend_api_key:
        return {"error": "Resend is not configured"}
    resp = await get_client().get(
        f"https://api.resend.com/emails/{message_id}",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
    )
    if resp.status_code >= 400:
        return {"error": f"Resend API error {resp.status_code}: {resp.text[:300]}"}
    return resp.json()


async def send_to_kindle(book_id: str, user_id: str) -> dict[str, Any]:
    """Send a book to Kindle via email."""
    user = await fetch_one("SELECT * FROM users WHERE id = $1", UUID(user_id))
    if not user or not user["kindle_email"]:
        return {"error": "No Kindle email configured"}

    # Check if workbook — send PDF instead of EPUB
    book = await fetch_one(
        """SELECT b.title, b.isbn, b.is_workbook, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
           FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE b.id = $1 GROUP BY b.id""",
        UUID(book_id),
    )
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

    from brainycat.filenames import build_filename

    ext = os.path.splitext(file_row["file_name"])[1]
    attachment_name = build_filename(title, book["authors"] if book else None, book["isbn"] if book else None, ext)

    body = f"Sent from BrainyCat: {title}"
    with open(file_row["file_path"], "rb") as f:
        content = f.read()

    if settings.resend_api_key:
        result = await _resend_send(to=user["kindle_email"], subject=title, text=body, filename=attachment_name, content=content)
        if "error" in result:
            return result
        return {"ok": True, "sent_to": user["kindle_email"], "format": file_row["format"], "message_id": result.get("id")}

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = _smtp_from()
    msg["To"] = user["kindle_email"]
    msg.set_content(body)
    mime = "application/epub+zip" if file_row["format"] == "epub" else "application/pdf"
    msg.add_attachment(content, maintype="application", subtype=mime.split("/")[1], filename=attachment_name)

    try:
        await _smtp_send(msg)
    except Exception as e:
        return {"error": f"SMTP send failed: {e}"}
    return {"ok": True, "sent_to": user["kindle_email"], "format": file_row["format"]}


async def send_to_device(book_id: str, email: str) -> dict[str, Any]:
    """Send a book to any email address."""
    file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
    if not file_row:
        return {"error": "No EPUB file"}

    book = await fetch_one(
        """SELECT b.title, b.isbn, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
           FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE b.id = $1 GROUP BY b.id""",
        UUID(book_id),
    )
    title = book["title"] if book else "Book"

    from brainycat.filenames import build_filename

    ext = os.path.splitext(file_row["file_name"])[1]
    attachment_name = build_filename(title, book["authors"] if book else None, book["isbn"] if book else None, ext)

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = _smtp_from()
    msg["To"] = email
    msg.set_content(f"Sent from BrainyCat: {title}")

    with open(file_row["file_path"], "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="epub+zip", filename=attachment_name)

    try:
        await _smtp_send(msg)
    except Exception as e:
        return {"error": f"SMTP send failed: {e}"}
    return {"ok": True, "sent_to": email}
