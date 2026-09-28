"""Standardized book filenames — 'Author - Title [ISBN].ext' — shared by downloads and on-disk renaming."""

from __future__ import annotations

import re


def safe_filename(s: str, max_len: int = 80) -> str:
    """Sanitize a string for use in a filename."""
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", " ", s).strip(". ")
    return s[:max_len].strip()


def build_filename(title: str | None, authors: list[str] | None, isbn: str | None, ext: str) -> str:
    """Build a standardized 'Author - Title [ISBN].ext' filename from current book metadata."""
    clean_title = safe_filename(title or "Unknown")
    clean_author = safe_filename((authors or ["Unknown"])[0])
    name = f"{clean_author} - {clean_title}"
    if isbn:
        name += f" [{isbn}]"
    return name + ext
