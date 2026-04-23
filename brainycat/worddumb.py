"""WordDumb — Word Wise + X-Ray generation for books.

Word Wise: annotate difficult words with simple definitions.
X-Ray: extract characters, locations, terms → reference card.
Uses LLM via Intello for definitions and NER for entity extraction.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from uuid import UUID

from brainycat.config import settings
from brainycat.db import execute, fetch_one
from brainycat.http_client import get_client


async def generate_word_wise(book_id: str) -> dict[str, Any]:
    """Generate Word Wise annotations for difficult words in a book."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub"}

    # Extract text
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
    words: Counter[str] = Counter()
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        for w in re.findall(r"[a-zA-Z]{6,}", text):
            words[w.lower()] += 1

    # Find uncommon words (appear 1-3 times, likely difficult)
    difficult = [w for w, c in words.items() if 1 <= c <= 3 and len(w) >= 7][:100]

    if not difficult:
        return {"words": 0}

    # Get definitions via LLM
    prompt = f"Define these words simply (1 short sentence each, for a reader):\n{', '.join(difficult[:50])}"
    definitions: dict[str, str] = {}
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {settings.intello_api_key}"},
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"]
            for line in text.split("\n"):
                m = re.match(r"\*?\*?(\w+)\*?\*?\s*[-:\u2013]\s*(.+)", line.strip())
                if m:
                    definitions[m.group(1).lower()] = m.group(2).strip()
    except Exception:
        pass

    # Store as book metadata
    await execute(
        "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
        f'{{"word_wise": {len(definitions)}}}',
        UUID(book_id),
    )

    return {"words": len(definitions), "definitions": definitions}


async def generate_xray(book_id: str) -> dict[str, Any]:
    """Generate X-Ray data: characters, locations, terms."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub"}

    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
    full_text = ""
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        full_text += soup.get_text(separator=" ", strip=True) + "\n"

    # Use LLM to extract entities
    sample = full_text[:8000]
    prompt = f"""From this book excerpt, extract:
1. CHARACTERS: name and brief description
2. LOCATIONS: name and context
3. KEY TERMS: important concepts

Format as JSON: {{"characters": [{{"name": "...", "desc": "..."}}], "locations": [...], "terms": [...]}}

Text: {sample}"""

    xray: dict[str, Any] = {"characters": [], "locations": [], "terms": []}
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {settings.intello_api_key}"},
        )
        if resp.status_code == 200:
            import json

            text = resp.json()["choices"][0]["message"]["content"]
            # Extract JSON from response
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                xray = json.loads(json_match.group())
    except Exception:
        pass

    await execute(
        "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
        f'{{"xray_characters": {len(xray.get("characters", []))}}}',
        UUID(book_id),
    )

    return xray
