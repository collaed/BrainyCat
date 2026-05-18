"""ComicInfo.xml parser — extract metadata from CBZ/CBR comic archives."""

from __future__ import annotations

import zipfile
from typing import Any
from xml.etree import ElementTree as ET


def parse_comicinfo(cbz_path: str) -> dict[str, Any]:
    """Extract metadata from ComicInfo.xml inside a CBZ file."""
    try:
        with zipfile.ZipFile(cbz_path) as zf:
            # Find ComicInfo.xml (case-insensitive)
            ci_name = next((n for n in zf.namelist() if n.lower() == "comicinfo.xml"), None)
            if not ci_name:
                return {}
            raw = zf.read(ci_name)
    except Exception:
        return {}

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}

    def _text(tag: str) -> str | None:
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    meta: dict[str, Any] = {}
    meta["title"] = _text("Title")
    meta["series"] = _text("Series")
    meta["series_index"] = _text("Number")
    meta["author"] = _text("Writer")
    meta["authors"] = list(filter(None, [
        _text("Writer"), _text("Penciller"), _text("Inker"),
        _text("Colorist"), _text("Letterer"),
    ]))
    meta["description"] = _text("Summary")
    meta["publisher"] = _text("Publisher")
    meta["language"] = _text("LanguageISO")
    meta["year"] = _text("Year")
    meta["genre"] = _text("Genre")
    meta["page_count"] = _text("PageCount")
    meta["age_rating"] = _text("AgeRating")
    meta["manga"] = _text("Manga")  # "Yes", "No", "YesAndRightToLeft"

    # Tags from Genre field (comma-separated)
    genre = _text("Genre")
    if genre:
        meta["tags"] = [g.strip() for g in genre.split(",") if g.strip()]

    return {k: v for k, v in meta.items() if v}
