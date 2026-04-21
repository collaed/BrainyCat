"""Filesystem storage operations."""

from __future__ import annotations

import os
import shutil

from brainycat.config import settings


def book_dir(book_id: str) -> str:
    """Return the directory for a book's files."""
    path = os.path.join(settings.data_dir, book_id)
    os.makedirs(path, exist_ok=True)
    return path


async def save_upload(book_id: str, filename: str, content: bytes) -> str:
    """Save uploaded file, return path. Strips directory components from filename."""
    safe_name = os.path.basename(filename)  # Strip any directory path
    d = book_dir(book_id)
    path = os.path.join(d, safe_name)
    with open(path, "wb") as f:
        f.write(content)
    return path


def delete_book_dir(book_id: str) -> None:
    """Remove a book's directory."""
    d = os.path.join(settings.data_dir, book_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
