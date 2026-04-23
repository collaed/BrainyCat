"""ISBN Range Message parser — official routing table from isbn-international.org.

Parses the 285 registration groups to map any ISBN to its country/agency.
Download: https://www.isbn-international.org/export_rangemessage.xml
Cache locally, refresh monthly.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

_groups: list[dict[str, Any]] = []


def load_ranges(xml_path: str = "/data/isbn_ranges.xml") -> int:
    """Parse ISBN Range Message XML. Returns number of groups loaded."""
    global _groups
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        _groups = []
        for g in root.findall(".//Group"):
            prefix = g.findtext("Prefix", "").strip()
            agency = g.findtext("Agency", "").strip()
            if prefix and agency:
                _groups.append({"prefix": prefix, "agency": agency, "flat": prefix.replace("-", "")})
        # Sort by prefix length descending for longest-match-first
        _groups.sort(key=lambda x: len(x["flat"]), reverse=True)
        return len(_groups)
    except Exception:
        return 0


def lookup(isbn: str) -> dict[str, str] | None:
    """Look up ISBN in the range message. Returns {prefix, agency}."""
    if not _groups:
        load_ranges()
    if not isbn or len(isbn) < 10:
        return None
    for g in _groups:
        if isbn.startswith(g["flat"]):
            return {"prefix": g["prefix"], "agency": g["agency"]}
    return None
