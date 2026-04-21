"""Format conversion (Calibre CLI) and Kindle delivery (SMTP)."""

from __future__ import annotations

import asyncio
import os
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import aiosmtplib

from brainycat.config import settings
from brainycat.db import execute, fetch_one


async def convert_format(book_id: str, target_format: str) -> dict[str, Any]:
    """Convert a book file to another format using Calibre."""
    row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
    if not row:
        return {"error": "No EPUB source file"}

    src = row["file_path"]
    base = os.path.splitext(src)[0]
    dest = f"{base}.{target_format}"

    proc = await asyncio.create_subprocess_exec(
        "ebook-convert",
        src,
        dest,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0 or not os.path.isfile(dest):
        return {"error": f"Conversion failed: {stderr.decode()[:200]}"}

    new_id = uuid4()
    await execute(
        """INSERT INTO book_files (id, book_id, format, file_path, file_name, file_size)
           VALUES ($1,$2,$3,$4,$5,$6)""",
        new_id,
        UUID(book_id),
        target_format,
        dest,
        os.path.basename(dest),
        os.path.getsize(dest),
    )
    return {"file_id": str(new_id), "format": target_format, "path": dest}


async def send_to_kindle(book_id: str, user_id: str) -> dict[str, Any]:
    """Send a book to Kindle via email."""
    user = await fetch_one("SELECT * FROM users WHERE id = $1", UUID(user_id))
    if not user or not user["kindle_email"]:
        return {"error": "No Kindle email configured"}

    # Find EPUB file (Kindle accepts EPUB now)
    file_row = await fetch_one("SELECT * FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1", UUID(book_id))
    if not file_row:
        return {"error": "No EPUB file available"}

    book = await fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
    title = book["title"] if book else "Book"

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = f"brainycat@{settings.smtp_host.replace('mailserver', 'ecb.pm')}"
    msg["To"] = user["kindle_email"]
    msg.set_content(f"Sent from BrainyCat: {title}")

    with open(file_row["file_path"], "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="epub+zip", filename=file_row["file_name"])

    await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port, use_tls=False)
    return {"ok": True, "sent_to": user["kindle_email"]}


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
