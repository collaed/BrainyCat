"""Library of Congress — via SRU/LCDB endpoint (not blocked by Cloudflare)."""

from __future__ import annotations

import re
from typing import Any

from brainycat.http_client import get_client

# lx2.loc.gov is LoC's direct SRU server (not behind Cloudflare)
SRU_URL = "https://lx2.loc.gov/sru/lcdb"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Search Library of Congress via SRU/MODS."""
    if isbn:
        query = f"bath.isbn={isbn}"
    elif title:
        query = f'bath.title="{title}"'
    else:
        return None

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": query,
        "maximumRecords": "1",
        "recordSchema": "mods",
    }

    try:
        client = get_client()
        resp = await client.get(SRU_URL, params=params, timeout=8)
        if resp.status_code != 200:
            return None
        xml = resp.text
    except Exception:
        return None

    # Check if we got results
    if "<zs:numberOfRecords>0</zs:numberOfRecords>" in xml:
        return None

    # Parse MODS XML (simple regex — avoids lxml dependency)
    def extract(tag: str) -> str | None:
        # Handle namespaced and non-namespaced
        m = re.search(rf"<(?:mods:)?{tag}[^>]*>([^<]+)</(?:mods:)?{tag}>", xml)
        return m.group(1).strip() if m else None

    def extract_all(tag: str) -> list[str]:
        return [m.strip() for m in re.findall(rf"<(?:mods:)?{tag}[^>]*>([^<]+)</(?:mods:)?{tag}>", xml)]

    title_found = extract("title")
    if not title_found:
        return None

    authors = extract_all("namePart")
    publisher = extract("publisher")
    date_issued = extract("dateIssued")
    subjects = extract_all("topic")
    lccn = None
    lccn_match = re.search(r'<(?:mods:)?identifier type="lccn">([^<]+)', xml)
    if lccn_match:
        lccn = lccn_match.group(1).strip()

    return {
        "title": title_found,
        "authors": authors[:3],
        "publisher": publisher,
        "pubdate": date_issued,
        "subjects": subjects[:10],
        "lccn": lccn,
        "source": "loc_sru",
    }
