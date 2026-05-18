"""Pre-enrichment content guard — sample 3 pages to detect language and genre.

Runs early in the pipeline (after import, before enrichment) to establish
ground-truth signals that can later validate or reject enrichment results.
"""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one


async def detect_content_signals(book_id: str) -> dict[str, Any]:
    """Sample pages at 25%, 50%, 75% of the book to detect language and genre."""
    file_row = await fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 ORDER BY created_at LIMIT 1",
        UUID(book_id),
    )
    if not file_row or not os.path.isfile(file_row["file_path"]):
        return {"ok": False}

    fmt = file_row["format"]
    path = file_row["file_path"]

    samples = []
    if fmt == "epub":
        samples = _sample_epub(path)
    elif fmt == "pdf":
        samples = _sample_pdf(path)

    if not samples:
        return {"ok": False}

    text = "\n".join(samples)

    # Detect language
    lang = _detect_language(text)

    # Detect genre signals
    genre = _detect_genre(text)

    # Store as pre-enrichment signals
    import json
    await execute(
        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{content_signals}', $1::jsonb) WHERE id = $2",
        json.dumps({"detected_language": lang, "detected_genre": genre, "sample_length": len(text)}),
        UUID(book_id),
    )
    return {"ok": True, "language": lang, "genre": genre}


def _sample_epub(path: str) -> list[str]:
    """Extract text from 3 positions (25%, 50%, 75%) of an EPUB."""
    import zipfile
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []
        def handle_data(self, data):
            self.text.append(data)

    try:
        with zipfile.ZipFile(path) as zf:
            html_files = [n for n in zf.namelist() if n.endswith(('.xhtml', '.html', '.htm')) and 'toc' not in n.lower()]
            if not html_files:
                return []
            positions = [max(0, int(len(html_files) * p) - 1) for p in (0.25, 0.5, 0.75)]
            samples = []
            for idx in positions:
                if idx < len(html_files):
                    raw = zf.read(html_files[idx]).decode("utf-8", errors="ignore")
                    ext = TextExtractor()
                    ext.feed(raw)
                    chunk = " ".join(ext.text).strip()
                    samples.append(chunk[:2000])
            return samples
    except Exception:
        return []


def _sample_pdf(path: str) -> list[str]:
    """Extract text from 3 positions of a PDF using pdftotext."""
    import subprocess
    try:
        result = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=10)
        pages = 0
        for line in result.stdout.splitlines():
            if line.startswith("Pages:"):
                pages = int(line.split(":")[1].strip())
                break
        if pages < 4:
            return []
        positions = [max(1, int(pages * p)) for p in (0.25, 0.5, 0.75)]
        samples = []
        for p in positions:
            r = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), path, "-"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                samples.append(r.stdout[:2000])
        return samples
    except Exception:
        return []


def _detect_language(text: str) -> str | None:
    """Simple language detection from text sample."""
    # Common word frequency approach
    text_lower = text.lower()
    scores: dict[str, int] = {}

    markers = {
        "fr": ["le", "la", "les", "de", "des", "un", "une", "est", "dans", "pour", "qui", "que", "avec", "sur", "pas", "sont", "cette", "mais", "aussi"],
        "en": ["the", "and", "is", "in", "to", "of", "that", "it", "was", "for", "with", "are", "this", "have", "from", "they", "been", "would", "which"],
        "de": ["der", "die", "das", "und", "ist", "ein", "eine", "nicht", "sich", "mit", "auf", "auch", "den", "dem", "noch", "nach", "wird", "bei", "einer"],
        "es": ["el", "la", "los", "las", "de", "en", "que", "por", "con", "una", "del", "para", "como", "pero", "más", "este", "entre", "cuando", "sobre"],
        "it": ["il", "la", "di", "che", "non", "una", "per", "sono", "con", "del", "della", "anche", "questo", "come", "più", "nella", "dalla", "essere"],
    }

    words = set(re.findall(r'\b[a-zàâäéèêëïîôùûüÿçñß]{2,6}\b', text_lower))
    for lang, lang_markers in markers.items():
        scores[lang] = sum(1 for m in lang_markers if m in words)

    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 5 else None


def _detect_genre(text: str) -> str | None:
    """Rough genre detection from content signals."""
    text_lower = text.lower()

    genre_signals = {
        "fiction": ["said", "she", "he", "looked", "walked", "door", "room", "eyes", "smiled", "dit", "elle", "il", "regarda", "porte"],
        "technology": ["function", "class", "code", "server", "database", "api", "software", "algorithm", "system", "data"],
        "science": ["experiment", "hypothesis", "research", "study", "results", "method", "analysis", "theory", "observed"],
        "self-help": ["mindset", "habit", "goal", "success", "motivation", "practice", "improve", "achieve", "focus", "routine"],
        "history": ["century", "war", "king", "empire", "revolution", "dynasty", "battle", "reign", "siècle", "guerre"],
        "philosophy": ["consciousness", "existence", "moral", "ethics", "truth", "reason", "being", "knowledge", "virtue"],
        "romance": ["kiss", "love", "heart", "passion", "desire", "embrace", "baiser", "amour", "coeur", "désir"],
        "thriller": ["gun", "murder", "detective", "suspect", "crime", "blood", "dead", "weapon", "arme", "mort", "sang"],
    }

    scores: dict[str, int] = {}
    for genre, signals in genre_signals.items():
        scores[genre] = sum(text_lower.count(s) for s in signals)

    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 3 else None
