"""Book summaries — structured knowledge extraction with progressive depth.

Level 1 (instant, no LLM): One-liner + 3 takeaways from title + description
Level 2 (on demand): Full structured summary from first 25K chars
Level 3 (background): Chapter-by-chapter + quotes + references + vocabulary

Fiction vs non-fiction: different formats, auto-detected from genre.
Supports any OpenAI-compatible API (Intello, Ollama, OpenRouter).
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import httpx

from brainycat.config import settings
from brainycat.db import execute, fetch_one

# Few-shot examples using public domain books (our own writing)
NONFICTION_EXAMPLE = """{
  "one_liner": "A 2,500-year-old treatise arguing that wars are won through strategy and understanding your enemy, not brute force.",
  "key_insight": "The supreme art of war is to subdue the enemy without fighting.",
  "takeaways": [
    "Know your enemy and know yourself — in 100 battles you will never be defeated",
    "All warfare is based on deception — appear weak when strong, strong when weak",
    "The best victory is one that requires no battle at all",
    "Speed is the essence of war — take advantage of the enemy's unreadiness",
    "Treat your soldiers as your own children and they will follow you into the deepest valleys"
  ],
  "who_should_read": "Leaders, strategists, and anyone navigating competitive environments",
  "counterpoint": "Critics note the text assumes a hierarchical military context that doesn't always map to modern collaborative environments."
}"""

FICTION_EXAMPLE = """{
  "one_liner": "A sharp social comedy about the Bennet sisters navigating love, class, and first impressions in Regency England.",
  "themes": ["class and social mobility", "pride vs prejudice", "marriage as economic necessity", "self-knowledge"],
  "mood": "witty, romantic, gently satirical",
  "writing_style": "Ironic third-person narration with sharp dialogue and social observation",
  "comparable_titles": ["North and South by Gaskell", "Emma by Austen", "Bridget Jones's Diary"],
  "content_warnings": [],
  "who_should_read": "Anyone who enjoys character-driven stories about relationships and social dynamics"
}"""


def _is_fiction(tags: list[str], description: str) -> bool:
    """Detect if a book is fiction based on tags and description."""
    fiction_signals = {
        "fiction",
        "novel",
        "romance",
        "thriller",
        "fantasy",
        "sci-fi",
        "mystery",
        "horror",
        "literary",
        "adventure",
        "drama",
        "erotica",
    }
    tag_set = {t.lower() for t in tags}
    return bool(tag_set & fiction_signals)


async def _llm_call(prompt: str) -> str | None:
    """Call any OpenAI-compatible API (Intello, Ollama, OpenRouter)."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": prompt}]},
                headers={"Authorization": f"Bearer {settings.intello_api_key}"},
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None


async def summary_level1(book_id: str) -> dict[str, Any]:
    """Level 1: Instant summary from title + description only. No LLM needed."""
    row = await fetch_one(
        """
        SELECT b.title, b.description,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM books b
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        UUID(book_id),
    )
    if not row:
        return {"error": "not found"}

    desc = (row["description"] or "")[:500]
    tags = row["tags"] or []
    fiction = _is_fiction(tags, desc)

    return {
        "level": 1,
        "type": "fiction" if fiction else "non-fiction",
        "title": row["title"],
        "tags": tags[:10],
        "description_preview": desc,
        "note": "Level 1: based on metadata only. Request Level 2 for full summary.",
    }


async def summary_level2(book_id: str) -> dict[str, Any]:
    """Level 2: Full structured summary via LLM. Cached."""
    # Check cache
    cached = await fetch_one(
        "SELECT extra_metadata->'summary' as s FROM books WHERE id = $1",
        UUID(book_id),
    )
    if cached and cached["s"]:
        try:
            data = json.loads(cached["s"]) if isinstance(cached["s"], str) else cached["s"]
            if data.get("level") == 2:
                return data
        except (json.JSONDecodeError, TypeError):
            pass

    # Get book text + metadata
    row = await fetch_one(
        """
        SELECT b.title, b.description,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE b.id = $1 GROUP BY b.id
    """,
        UUID(book_id),
    )
    if not row:
        return {"error": "not found"}

    text = await _get_book_text(book_id)
    tags = row["tags"] or []
    fiction = _is_fiction(tags, row["description"] or "")

    if fiction:
        prompt = f"""You are a professional book reviewer. Analyze this fiction book.
Return JSON matching this exact format (based on Pride and Prejudice):
{FICTION_EXAMPLE}

Book: {row["title"]} by {", ".join(row["authors"] or [])}
Text (first 25K chars):
{text[:25000]}"""
    else:
        prompt = f"""You are a professional book summarizer (like getAbstract).
Return JSON matching this exact format (based on The Art of War):
{NONFICTION_EXAMPLE}

Also include:
- "chapter_summaries": [{{"chapter": "name", "summary": "2-3 sentences"}}]
- "actionable_insights": ["3-5 concrete things to do based on this book"]
- "reading_time_saved": "Xh → Y minutes"

Book: {row["title"]} by {", ".join(row["authors"] or [])}
Text (first 25K chars):
{text[:25000]}"""

    content = await _llm_call(prompt)
    if not content:
        return {"error": "LLM unavailable — summaries require Intello, Ollama, or OpenAI-compatible API"}

    # Parse JSON from response
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {"error": "LLM returned non-JSON response"}

    try:
        summary = json.loads(m.group())
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON"}

    summary["level"] = 2
    summary["type"] = "fiction" if fiction else "non-fiction"

    # Cache
    await execute(
        "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{summary}', $1::jsonb) WHERE id = $2",
        json.dumps(summary),
        UUID(book_id),
    )
    return summary


async def goldmine(book_id: str) -> dict[str, Any]:
    """Level 3: Deep knowledge extraction — quotes, references, vocabulary."""
    text = await _get_book_text(book_id)
    if not text:
        return {"error": "no text available"}

    prompt = f"""Extract knowledge from this book text. Return JSON:
{{
  "quotable_passages": ["5 most memorable/quotable sentences from the text"],
  "referenced_works": ["books, papers, or works mentioned or cited in this text"],
  "key_vocabulary": [{{"term": "word", "definition": "meaning in context"}}],
  "action_items": ["concrete things a reader could do based on this book"]
}}

Text (first 30K chars):
{text[:30000]}"""

    content = await _llm_call(prompt)
    if not content:
        return {"error": "LLM unavailable"}

    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"error": "extraction failed"}


async def _get_book_text(book_id: str) -> str:
    """Extract text from a book's EPUB file."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return ""
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text(separator=" ", strip=True) + "\n"
            if len(text) > 30000:
                break
        return text
    except Exception:
        return ""
