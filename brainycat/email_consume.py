"""Email consumption — poll IMAP inbox for ebook attachments and import them."""

from __future__ import annotations

import email
import imaplib
import os
import tempfile
from email.header import decode_header
from typing import Any

from brainycat.config import settings
from brainycat.logging import log
from brainycat.watcher import ALLOWED_EXT, _import_file


async def check_email_inbox() -> dict[str, int]:
    """Connect to IMAP, find emails with ebook attachments, import them."""
    host = getattr(settings, "imap_host", "")
    user = getattr(settings, "imap_user", "")
    password = getattr(settings, "imap_password", "")
    folder = getattr(settings, "imap_folder", "INBOX")

    if not host or not user or not password:
        return {"skipped": True, "reason": "IMAP not configured"}

    imported = 0
    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select(folder)

        _, msg_ids = mail.search(None, "UNSEEN")
        for msg_id in msg_ids[0].split():
            if not msg_id:
                continue
            _, data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                if not filename:
                    continue

                # Decode filename
                decoded = decode_header(filename)
                fname = ""
                for chunk, enc in decoded:
                    if isinstance(chunk, bytes):
                        fname += chunk.decode(enc or "utf-8", errors="ignore")
                    else:
                        fname += chunk

                ext = os.path.splitext(fname)[1].lower()
                if ext not in ALLOWED_EXT:
                    continue

                # Save attachment to incoming folder
                content = part.get_payload(decode=True)
                if not content:
                    continue

                dest = os.path.join(settings.incoming_dir, fname)
                with open(dest, "wb") as f:
                    f.write(content)

                # Import directly
                try:
                    await _import_file(dest)
                    imported += 1
                except Exception as e:
                    await log.awarning("email_import_error", file=fname, error=str(e)[:80])

            # Mark as seen
            mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        return {"error": str(e)[:200]}

    return {"imported": imported}
