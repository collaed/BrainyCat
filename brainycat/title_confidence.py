"""Title confidence scoring and publisher series detection.

Improves enrichment queries by:
1. Detecting publisher from series patterns (Head First → O'Reilly, In a Nutshell → O'Reilly)
2. Stripping user markers (trailing 'u' for unprotected)
3. Extracting high-confidence title from PDF first pages (standalone line = likely title)
4. Normalizing case for API queries
"""

from __future__ import annotations

import re
from typing import Any

# Series → Publisher mapping for enrichment query boosting
SERIES_PUBLISHER_MAP: dict[str, str] = {
    # O'Reilly
    "Head First": "O'Reilly",
    "In a Nutshell": "O'Reilly",
    "Cookbook": "O'Reilly",
    "Programming": "O'Reilly",
    "Learning": "O'Reilly",
    # Packt
    "Mastering": "Packt",
    "Hands-On": "Packt",
    "Building": "Packt",
    # Wiley / For Dummies
    "For Dummies": "Wiley",
    "Dummies": "Wiley",
    # Sams
    "in 24 Hours": "Sams",
    "Teach Yourself": "Sams",
    "in 21 Days": "Sams",
    # Apress
    "Pro ": "Apress",
    "Beginning ": "Apress",
    "Expert ": "Apress",
    # Manning
    "in Action": "Manning",
    "in Practice": "Manning",
    # Pragmatic
    "Pragmatic": "Pragmatic Bookshelf",
}


def detect_publisher(title: str) -> str | None:
    """Detect likely publisher from title patterns."""
    for pattern, publisher in SERIES_PUBLISHER_MAP.items():
        if pattern.lower() in title.lower():
            return publisher
    return None


def clean_title_for_query(title: str) -> str:
    """Clean a title for API queries: strip markers, normalize case."""
    t = title.strip()

    # Strip "Downloads/" prefix
    if t.startswith("Downloads/"):
        t = t[10:]

    # Strip trailing " u" (unprotected marker)
    if t.endswith(" u"):
        t = t[:-2]

    # Strip "O'Reilly - " prefix
    t = re.sub(r"^O'Reilly\s*[-–]\s*", "", t)

    # Strip file extensions
    t = re.sub(r"\.\w{2,4}$", "", t)

    # Strip bracketed content at start [Series Name]
    t = re.sub(r"^\[[^\]]+\]\s*", "", t)

    # Strip "Author - " prefix pattern
    t = re.sub(r"^[A-Z][a-z]+,?\s+[A-Z][a-z]+\s*[-–]\s*", "", t)

    # Normalize case: if ALL CAPS or all lower, convert to title case
    if t.isupper() or t.islower():
        t = t.title()

    return t.strip()


def build_enrichment_query(title: str) -> str:
    """Build the best possible search query from a title."""
    clean = clean_title_for_query(title)
    publisher = detect_publisher(clean)
    if publisher:
        return f"{clean} {publisher}"
    return clean


async def extract_title_from_content(file_path: str, format: str = "pdf") -> str | None:
    """Extract high-confidence title from first 20 pages.

    Heuristic: a short line (2-8 words) that appears alone (surrounded by
    whitespace/short lines) on one of the first 20 pages is likely the title.
    Bonus confidence if it's on pages 1-5 and in larger font (PDF) or <h1> (EPUB).
    """
    if format == "pdf":
        import fitz

        try:
            doc = fitz.open(file_path)
        except Exception:
            return None

        candidates: list[tuple[str, float]] = []

        for page_num in range(min(20, len(doc))):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if block.get("type") != 0:  # text blocks only
                    continue
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line.get("spans", [])).strip()
                    font_size = max((span.get("size", 12) for span in line.get("spans", [])), default=12)
                    word_count = len(text.split())

                    # Title candidate: 2-10 words, larger font, early pages
                    if 2 <= word_count <= 10 and font_size >= 16:
                        # Score: bigger font + earlier page = higher confidence
                        score = font_size * (1 / (page_num + 1))
                        # Penalize if looks like header/footer
                        if any(
                            x in text.lower()
                            for x in [
                                "page",
                                "chapter",
                                "table of",
                                "copyright",
                                "isbn",
                                "by ",
                                "edition",
                                "published",
                                "press",
                                "all rights",
                            ]
                        ):
                            continue
                        candidates.append((text, score))

        doc.close()

        if candidates:
            # Return highest-scoring candidate
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]

    elif format == "epub":
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        try:
            book = epub.read_epub(file_path, options={"ignore_ncx": True})
        except Exception:
            return None

        # Check first 3 items for <h1> or <title>
        for item in list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))[:3]:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            h1 = soup.find("h1")
            if h1:
                text = h1.get_text().strip()
                if 2 <= len(text.split()) <= 10:
                    return text

    return None
