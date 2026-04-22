"""OCLC Classify API — gold standard for DDC/LCC classification."""

from __future__ import annotations

from typing import Any

import httpx

API_URL = "http://classify.oclc.org/classify2/Classify"


async def search(title: str | None = None, isbn: str | None = None) -> dict[str, Any] | None:
    """Query OCLC Classify for DDC/LCC classification."""
    params: dict[str, Any] = {"summary": "true"}
    if isbn:
        params["isbn"] = isbn
    elif title:
        params["title"] = title
    else:
        return None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # JSON endpoint
            params["jsonp"] = ""
            resp = await client.get(API_URL, params=params)
            if resp.status_code != 200:
                return None

            # OCLC returns JSONP or XML — try to parse
            text = resp.text.strip()
            if text.startswith("(") or text.startswith("{"):
                # Try JSON
                import json

                text = text.strip("();")
                json.loads(text)
            else:
                # Parse XML
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(text, "html.parser")
                work = soup.find("work")
                if not work:
                    return None

                ddc = soup.find("mostpopular", {"sfa": True})
                lcc = soup.find("mostpopular", {"nsfa": True})

                return {
                    "source": "oclc",
                    "title": work.get("title"),
                    "ddc": ddc.get("sfa") if ddc else None,
                    "lcc": lcc.get("nsfa") if lcc else None,
                    "authors": [work.get("author")] if work.get("author") else [],
                    "genres": _ddc_to_thema(ddc.get("sfa") if ddc else None),
                    "owi": work.get("owi"),
                }
    except Exception:
        pass
    return None


def _ddc_to_thema(ddc: str | None) -> list[str]:
    """Map Dewey Decimal to approximate Thema subject codes."""
    if not ddc:
        return []
    try:
        num = int(ddc.split(".")[0])
    except (ValueError, IndexError):
        return [ddc]

    # Top-level DDC → Thema mapping
    mapping = {
        range(0, 100): "GP",  # Computer science, information
        range(100, 200): "QD",  # Philosophy & psychology
        range(200, 300): "QR",  # Religion
        range(300, 400): "JB",  # Social sciences
        range(400, 500): "CF",  # Language
        range(500, 600): "PD",  # Science
        range(600, 700): "T",  # Technology
        range(700, 800): "A",  # Arts
        range(800, 900): "F",  # Literature / Fiction
        range(900, 1000): "NH",  # History & geography
    }

    # More specific fiction mapping
    fiction_sub = {
        range(810, 820): "FA",  # American fiction
        range(820, 830): "FA",  # English fiction
        range(830, 840): "FA",  # German fiction
        range(840, 850): "FA",  # French fiction
        range(850, 860): "FA",  # Italian fiction
        range(860, 870): "FA",  # Spanish fiction
    }

    thema = []
    for r, code in fiction_sub.items():
        if num in r:
            thema.append(code)
            break
    if not thema:
        for r, code in mapping.items():
            if num in r:
                thema.append(code)
                break

    thema.append(f"DDC:{ddc}")
    return thema


# Thema code labels for display
THEMA_LABELS: dict[str, str] = {
    "F": "Fiction",
    "FA": "Fiction — General",
    "FB": "Fiction — General & Literary",
    "FC": "Fiction — Classic",
    "FD": "Fiction — Adventure",
    "FF": "Fiction — Crime & Mystery",
    "FH": "Fiction — Thriller",
    "FJ": "Fiction — Romance",
    "FK": "Fiction — Horror",
    "FL": "Fiction — Sci-Fi",
    "FM": "Fiction — Fantasy",
    "FN": "Fiction — War",
    "FP": "Fiction — Erotica",
    "FQ": "Fiction — Humour",
    "FR": "Fiction — Romance",
    "FX": "Fiction — Graphic Novels",
    "A": "Arts",
    "C": "Language",
    "CF": "Linguistics",
    "D": "Biography",
    "G": "Reference",
    "GP": "Computing & IT",
    "J": "Society & Social Sciences",
    "JB": "Society",
    "K": "Economics",
    "L": "Law",
    "M": "Medicine",
    "NH": "History",
    "NK": "Archaeology",
    "NP": "Geography",
    "P": "Mathematics & Science",
    "PD": "Science",
    "QD": "Philosophy",
    "QR": "Religion",
    "T": "Technology",
    "V": "Health",
    "VS": "Self-help",
    "W": "Lifestyle",
}
